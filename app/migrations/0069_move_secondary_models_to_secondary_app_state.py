from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0068_secondarycompetency_secondarycomputationpolicy_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name="CAModeration"),
                migrations.DeleteModel(name="ContinuousAssessmentRecord"),
                migrations.DeleteModel(name="ContinuousAssessmentTask"),
                migrations.DeleteModel(name="SecondaryGradeBand"),
                migrations.DeleteModel(name="SubjectCompetency"),
                migrations.DeleteModel(name="UNEBSubmissionItem"),
                migrations.DeleteModel(name="UNEBSubmissionBatch"),
                migrations.DeleteModel(name="SecondaryComputationPolicy"),
                migrations.DeleteModel(name="SecondaryCompetency"),
            ],
        ),
    ]
