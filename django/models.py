class MyModel(models.Model):
    # fields here

    def delete(self, *args, **kwargs):
        super(MyModel, self).delete(*args, **kwargs)
        if not self.has_dependencies():
            self.pk = None
