from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_accountsession_pendingemailchange")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="rebrickable_api_key_encrypted",
            field=models.TextField(blank=True),
        ),
    ]
