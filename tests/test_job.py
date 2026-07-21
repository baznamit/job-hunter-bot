from models import Job


def test_create_job():
    job = Job(
        id="123",
        title="Software Engineer",
        company="Postman",
        location="Bangalore",
        url="https://example.com/jobs/123",
    )

    assert job.id == "123"
    assert job.title == "Software Engineer"
    assert job.company == "Postman"
    assert job.remote is False