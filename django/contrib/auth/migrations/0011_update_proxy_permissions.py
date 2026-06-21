from django.db import migrations, transaction
from django.db.models import Q
from django.db import IntegrityError
import sys


def update_proxy_model_permissions(apps, schema_editor, reverse=False):
    """
    Update the content_type of proxy model permissions to use the ContentType
    of the proxy model.
    """
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    for Model in apps.get_models():
        opts = Model._meta
        if not opts.proxy:
            continue
        proxy_default_permissions_codenames = [
            '%s_%s' % (action, opts.model_name)
            for action in opts.default_permissions
        ]
        permissions_query = Q(codename__in=proxy_default_permissions_codenames)
        for codename, name in opts.permissions:
            permissions_query = permissions_query | Q(codename=codename, name=name)
        concrete_content_type = ContentType.objects.get_for_model(Model, for_concrete_model=True)
        proxy_content_type = ContentType.objects.get_for_model(Model, for_concrete_model=False)
        old_content_type = proxy_content_type if reverse else concrete_content_type
        new_content_type = concrete_content_type if reverse else proxy_content_type
        try:
            with transaction.atomic():
                # Get permissions that need to be updated
                perms_to_update = Permission.objects.filter(
                    permissions_query,
                    content_type=old_content_type,
                )
                # Delete any conflicting permissions that already exist for the new content type
                Permission.objects.filter(
                    permissions_query,
                    content_type=new_content_type,
                ).delete()
                # Now update the remaining permissions
                perms_to_update.update(content_type=new_content_type)
        except IntegrityError:
            old = "{}_{}" .format(old_content_type.app_label, old_content_type.model)
            new = "{}_{}" .format(new_content_type.app_label, new_content_type.model)
            sys.stdout.write(
                "WARNING: Could not update permissions for {} to {}. "
                "Permissions may already exist for the target content type.\n".format(old, new)
            )


def revert_proxy_model_permissions(apps, schema_editor):
    """
    Update the content_type of proxy model permissions to use the ContentType
    of the concrete model.
    """
    update_proxy_model_permissions(apps, schema_editor, reverse=True)


class Migration(migrations.Migration):
    dependencies = [
        ('auth', '0010_alter_group_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]
    operations = [
        migrations.RunPython(update_proxy_model_permissions, revert_proxy_model_permissions),
    ]
