class OnDeleteTests(TestCase):
    # Existing tests...

    def test_delete_model_pk_set_to_none(self):
        # Create a model instance
        a = create_a("test_instance")
        # Delete the instance
        a.delete()
        # Fetch the object again from the database
        a_fetched = A.objects.filter(pk=a.pk).first()
        # Check if PK is set to None after deletion
        self.assertIsNone(a_fetched.pk)
