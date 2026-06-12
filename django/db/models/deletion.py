# Regression tests for deletion behavior

from django.test import TestCase
from django.db import models

class TestModel(models.Model):
    name = models.CharField(max_length=100)

class DeletionTestCase(TestCase):
    def setUp(self):
        self.obj = TestModel.objects.create(name='Test')

    def test_delete_model(self):
        self.obj.delete()
        self.assertFalse(TestModel.objects.filter(id=self.obj.id).exists())

    def test_protected_delete(self):
        # Assuming there is a protected relationship, this should raise an error
        with self.assertRaises(ProtectedError):
            self.obj.delete()
