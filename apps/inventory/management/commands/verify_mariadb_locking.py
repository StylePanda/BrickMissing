from __future__ import annotations

import queue
import threading
import time
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, connection, transaction

from apps.audit.models import AuditEvent
from apps.inventory.models import InventoryItem, InventoryMovement
from apps.inventory.services import change_inventory


class Command(BaseCommand):
    help = "Verify real MariaDB row locking and concurrent inventory invariants."

    def handle(self, *args, **options):
        if connection.vendor != "mysql" or not connection.features.has_select_for_update:
            raise CommandError("This verification requires MariaDB with SELECT FOR UPDATE")
        suffix = uuid.uuid4().hex
        user = get_user_model().objects.create_user(
            username=f"locking-{suffix}",
            email=f"locking-{suffix}@example.invalid",
            password=None,
            email_verified=True,
        )
        item = InventoryItem.objects.create(
            owner=user, part_number=f"lock-{suffix}", name="Lock verification", quantity=5
        )
        try:
            self._verify_blocking_lock(item, user)
            self._verify_concurrent_deltas(item, user)
            self._verify_reservation_contention(item, user)
        finally:
            AuditEvent.objects.filter(actor=user).delete()
            InventoryMovement.objects.filter(item=item).delete()
            item.delete()
            user.delete()
            close_old_connections()
        self.stdout.write(self.style.SUCCESS("MariaDB locking verification: PASS"))

    def _worker(self, operation, results, started=None):
        close_old_connections()
        try:
            if started:
                started.set()
            operation()
        except BaseException as exc:
            results.put(exc)
        else:
            results.put(None)
        finally:
            close_old_connections()

    def _verify_blocking_lock(self, item, user):
        results: queue.Queue = queue.Queue()
        started = threading.Event()
        with transaction.atomic():
            InventoryItem.objects.select_for_update().get(pk=item.pk)
            worker = threading.Thread(
                target=self._worker,
                args=(
                    lambda: change_inventory(
                        item, user, quantity_delta=1, movement_type="locking-verification"
                    ),
                    results,
                    started,
                ),
                daemon=True,
            )
            worker.start()
            if not started.wait(2):
                raise CommandError("Concurrent locking worker did not start")
            time.sleep(0.25)
            if not results.empty():
                raise CommandError("SELECT FOR UPDATE did not block the concurrent writer")
        worker.join(5)
        if worker.is_alive():
            raise CommandError("Concurrent writer did not resume after lock release")
        failure = results.get_nowait()
        if failure:
            raise CommandError(f"Locking worker failed: {type(failure).__name__}")
        item.refresh_from_db()
        if item.quantity != 6:
            raise CommandError("Locked update produced an incorrect quantity")

    def _verify_concurrent_deltas(self, item, user):
        barrier = threading.Barrier(2)
        results: queue.Queue = queue.Queue()

        def delta(amount):
            barrier.wait(timeout=3)
            change_inventory(
                item, user, quantity_delta=amount, movement_type="concurrent-verification"
            )

        workers = [
            threading.Thread(target=self._worker, args=(lambda: delta(2), results), daemon=True),
            threading.Thread(target=self._worker, args=(lambda: delta(3), results), daemon=True),
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(5)
        failures = [results.get_nowait() for _ in workers]
        if any(failures) or any(worker.is_alive() for worker in workers):
            raise CommandError("Concurrent delta verification failed")
        item.refresh_from_db()
        if item.quantity != 11:
            raise CommandError("Concurrent delta update was lost")

    def _verify_reservation_contention(self, item, user):
        barrier = threading.Barrier(2)
        results: queue.Queue = queue.Queue()

        def reserve():
            barrier.wait(timeout=3)
            change_inventory(
                item, user, reserved_delta=7, movement_type="reservation-verification"
            )

        workers = [
            threading.Thread(target=self._worker, args=(reserve, results), daemon=True)
            for _ in range(2)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(5)
        outcomes = [results.get_nowait() for _ in workers]
        if sum(outcome is None for outcome in outcomes) != 1 or sum(
            isinstance(outcome, ValidationError) for outcome in outcomes
        ) != 1:
            raise CommandError("Reservation contention did not enforce stock invariants")
        item.refresh_from_db()
        if item.reserved_quantity != 7 or item.reserved_quantity > item.quantity:
            raise CommandError("Reservation contention produced an invalid state")
