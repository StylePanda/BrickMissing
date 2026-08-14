import hashlib

from django.db import migrations, models


def backfill_attribution(apps, schema_editor):
    AuditEvent = apps.get_model("audit", "AuditEvent")
    for event in AuditEvent.objects.select_related("actor", "target_user").iterator():
        fields = []
        if event.actor_id and event.actor:
            event.actor_identifier = str(event.actor_id)
            event.actor_username_snapshot = event.actor.username[:150]
            if event.actor.email:
                event.actor_email_hash = hashlib.sha256(
                    event.actor.email.strip().casefold().encode("utf-8")
                ).hexdigest()
            fields.extend(["actor_identifier", "actor_username_snapshot", "actor_email_hash"])
        if event.target_user_id and event.target_user:
            event.target_identifier = str(event.target_user_id)
            event.target_type = "accounts.User"
            event.target_repr_snapshot = event.target_user.username[:255]
            fields.extend(["target_identifier", "target_type", "target_repr_snapshot"])
        elif event.entity_type:
            event.target_type = event.entity_type[:100]
            fields.append("target_type")
        if fields:
            event.save(update_fields=fields)


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [
        migrations.AddField(model_name="auditevent", name="actor_email_hash", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="auditevent", name="actor_identifier", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="auditevent", name="actor_username_snapshot", field=models.CharField(blank=True, max_length=150)),
        migrations.AddField(model_name="auditevent", name="target_identifier", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="auditevent", name="target_repr_snapshot", field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name="auditevent", name="target_type", field=models.CharField(blank=True, max_length=100)),
        migrations.RunPython(backfill_attribution, migrations.RunPython.noop),
    ]
