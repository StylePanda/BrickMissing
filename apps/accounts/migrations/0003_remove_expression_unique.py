from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_user_totp_enabled_user_totp_secret_encrypted")]
    operations = [
        migrations.RemoveConstraint(
            model_name="user", name="accounts_user_email_ci_unique"
        )
    ]
