import django.db.models.deletion
from django.db import migrations, models


def populate_result_units(apps, schema_editor):
    MonthlyCompensationResult = apps.get_model("core", "MonthlyCompensationResult")
    for result in MonthlyCompensationResult.objects.select_related("compensation").iterator():
        result.unit_id = result.compensation.unit_id
        result.save(update_fields=["unit"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_admissionfielddefinition_admissionrequest_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="monthlycompensationresult",
            name="unique_monthly_compensation_result",
        ),
        migrations.RemoveConstraint(
            model_name="paymententry",
            name="unique_payment_entry_source",
        ),
        migrations.AddField(
            model_name="monthlycompensationresult",
            name="unit",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="monthly_compensation_results",
                to="core.unit",
            ),
        ),
        migrations.RunPython(populate_result_units, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="monthlycompensationresult",
            name="unit",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="monthly_compensation_results",
                to="core.unit",
            ),
        ),
        migrations.AlterModelOptions(
            name="monthlycompensationresult",
            options={"ordering": ["collaborator__name", "unit__name"]},
        ),
        migrations.AddConstraint(
            model_name="monthlycompensationresult",
            constraint=models.UniqueConstraint(
                fields=("competency", "collaborator", "unit"),
                name="unique_monthly_compensation_result",
            ),
        ),
        migrations.AddConstraint(
            model_name="paymententry",
            constraint=models.UniqueConstraint(
                fields=("cycle", "collaborator", "unit", "rubric", "source_event"),
                name="unique_payment_entry_source",
            ),
        ),
    ]
