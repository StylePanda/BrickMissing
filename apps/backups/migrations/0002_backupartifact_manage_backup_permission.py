from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("backups", "0001_initial")]

    operations = [
        migrations.AlterModelOptions(
            name="backupartifact",
            options={
                "ordering": ["-created_at"],
                "permissions": [("manage_backup", "Darf Backups verwalten")],
            },
        )
    ]
