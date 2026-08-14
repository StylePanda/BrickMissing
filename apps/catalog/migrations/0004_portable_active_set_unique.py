from django.db import migrations, models


def populate_active_numbers(apps, schema_editor):
    LegoSet = apps.get_model("catalog", "LegoSet")
    for item in LegoSet.objects.filter(deleted_at__isnull=True).iterator():
        item.active_set_number = item.set_number
        item.save(update_fields=["active_set_number"])


class Migration(migrations.Migration):
    dependencies = [("catalog", "0003_parthistory_legacy_id")]
    operations = [
        migrations.RemoveConstraint(
            model_name="legoset", name="unique_active_set_per_owner"
        ),
        migrations.AddField(
            model_name="legoset",
            name="active_set_number",
            field=models.CharField(editable=False, max_length=64, null=True),
        ),
        migrations.RunPython(populate_active_numbers, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="legoset",
            constraint=models.UniqueConstraint(
                fields=("owner", "active_set_number"),
                name="unique_active_set_per_owner",
            ),
        ),
    ]
