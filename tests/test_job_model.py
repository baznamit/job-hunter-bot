from models import Job


def test_job_model_creation():
    job = Job(
        id="123",
        title="Software Engineer",
        company="Postman",
        location="Bangalore",
        url="https://example.com/jobs/123",
    )

    assert job.id == "123"
    assert job.remote is False  