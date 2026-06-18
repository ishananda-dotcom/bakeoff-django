
def delete(self, using=None, keep_parents=False):
    if not self._is_pk_set():
        raise ValueError(
            "%s object can't be deleted because its %s attribute is set "
            "to None." % (self._meta.object_name, self._meta.pk.attname)
        )
    using = using or router.db_for_write(self.__class__, instance=self)
    collector = Collector(using=using, origin=self)
    collector.collect([self], keep_parents=keep_parents)

    # Set PK to None after deletion
    deleted = collector.delete()
    for model in deleted:
        model._set_pk_val(None)
    return deleted
