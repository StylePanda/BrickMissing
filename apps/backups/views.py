import zipfile

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate
from django.core.cache import cache
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEvent
from apps.core.rate_limit import limited

from .models import BackupArtifact
from .services import _root, create_backup, restore_backup, verify_backup


@staff_member_required
def backup_list(request):
    return render(request, "backups/list.html", {"backups": BackupArtifact.objects.all()})


@staff_member_required
@require_POST
def backup_create(request):
    if limited(request, "staff-backup", 5, 3600, per_user=True):
        return HttpResponse("Rate limit exceeded", status=429)
    artifact = create_backup(request.user)
    AuditEvent.objects.create(actor=request.user, action="backup.created", entity_type="backup", entity_id=str(artifact.pk), request_id=request.request_id)
    messages.success(request, "Verschlüsseltes Backup wurde erstellt.")
    return redirect("backups:list")


@staff_member_required
def backup_download(request, pk):
    artifact = get_object_or_404(BackupArtifact, pk=pk, status="ready")
    verify_backup(artifact)
    path = _root() / artifact.filename
    return FileResponse(path.open("rb"), as_attachment=True, filename=artifact.filename)


@staff_member_required
@require_POST
def backup_restore(request, pk):
    if limited(request, "staff-restore", 3, 3600, per_user=True):
        return HttpResponse("Rate limit exceeded", status=429)
    if not authenticate(request, username=request.user.get_username(), password=request.POST.get("password", "")):
        messages.error(request, "Passwortbestätigung fehlgeschlagen.")
        return redirect("backups:list")
    artifact = get_object_or_404(BackupArtifact, pk=pk, status="ready")
    verify_backup(artifact)
    safety = create_backup(request.user, enforce_retention=False)
    cache.set("maintenance_mode", True, 3600)
    try:
        restore_backup(artifact)
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        raise Http404("Backup ist ungültig") from exc
    finally:
        cache.delete("maintenance_mode")
    artifact.restored_at = timezone.now()
    artifact.save(update_fields=["restored_at"])
    AuditEvent.objects.create(
        actor=request.user, action="backup.restored", entity_type="backup",
        entity_id=str(artifact.pk),
        details={
            "safety_backup": safety.pk,
            "snapshot_semantics": "business-state-with-append-only-security-audit",
        },
        remote_address=getattr(request, "client_ip", None),
        request_id=request.request_id,
    )
    messages.success(request, "Backup wurde geprüft und wiederhergestellt.")
    return redirect("backups:list")
