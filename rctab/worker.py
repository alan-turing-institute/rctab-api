import logging

# from rctab.main import app as web_app
from celery import Celery
from celery.schedules import crontab

CELERY_BROKER_URL = "redis://localhost:6380/0"
CELERY_RESULT_BACKEND = "redis://localhost:6380/0"

celery_app = Celery(
    "rctab.worker",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)

# celery_app.conf.update(task_routes={'tasks.my_task': 'main_queue'})

celery_app.conf.beat_schedule = {
    "periodic-task": {
        "task": "rctab.tasks.my_task",
        "schedule": crontab(minute="0", hour="0"),  # adjust the schedule as needed
    },
    "thirty-seconds-task": {
        "task": "rctab.tasks.my_task",
        "schedule": 30.0,  # run every thirty seconds
    },
}
# @web_app.on_event("startup")
# def celery_setup():
#     celery_app.conf.update(
#         enable_utc=True,
#         timezone='UTC',
#     )

# @celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):

    # Calls test('hello') every 30 seconds.
    # It uses the same signature of previous task, an explicit name is
    # defined to avoid this task replacing the previous one defined.
    sender.add_periodic_task(30.0, test.s("hello"), name="add every 30")

    # Executes every Monday morning at 7:30 a.m.
    # sender.add_periodic_task(
    #     crontab(hour=7, minute=30, day_of_week=1),
    #     test.s('Happy Mondays!'),
    # )


# @celery_app.task
def test(arg):
    logging.warning(arg)
