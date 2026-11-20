# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alan-turing-institute/rctab-api/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                        |    Stmts |     Miss |   Cover |   Missing |
|-------------------------------------------- | -------: | -------: | ------: | --------: |
| rctab/\_\_init\_\_.py                       |        2 |        0 |    100% |           |
| rctab/constants.py                          |       13 |        0 |    100% |           |
| rctab/crud/\_\_init\_\_.py                  |        2 |        0 |    100% |           |
| rctab/crud/accounting\_models.py            |       26 |        0 |    100% |           |
| rctab/crud/auth.py                          |       61 |       30 |     51% |20-28, 33-45, 50-52, 96, 106-123, 137-143, 150-155 |
| rctab/crud/locks.py                         |       27 |        0 |    100% |           |
| rctab/crud/models.py                        |        5 |        0 |    100% |           |
| rctab/crud/utils.py                         |       14 |        0 |    100% |           |
| rctab/db.py                                 |       13 |        0 |    100% |           |
| rctab/debug.py                              |        4 |        4 |      0% |       3-8 |
| rctab/exceptions.py                         |        1 |        0 |    100% |           |
| rctab/logutils.py                           |       21 |       10 |     52% |16-17, 21-25, 41-46 |
| rctab/main.py                               |       81 |        7 |     91% |107, 154-155, 161, 170, 178, 184 |
| rctab/routers/\_\_init\_\_.py               |        0 |        0 |    100% |           |
| rctab/routers/accounting/\_\_init\_\_.py    |        2 |        0 |    100% |           |
| rctab/routers/accounting/abolishment.py     |       69 |       13 |     81% |83, 135, 174-198, 203-211 |
| rctab/routers/accounting/allocations.py     |       41 |        6 |     85% |28, 32, 38, 44, 115-116 |
| rctab/routers/accounting/approvals.py       |       69 |        4 |     94% |65, 98, 113, 119 |
| rctab/routers/accounting/cost\_recovery.py  |       74 |        0 |    100% |           |
| rctab/routers/accounting/desired\_states.py |       81 |       17 |     79% |43-72, 134-135 |
| rctab/routers/accounting/finances.py        |      101 |        1 |     99% |       231 |
| rctab/routers/accounting/persistence.py     |       22 |        0 |    100% |           |
| rctab/routers/accounting/routes.py          |      115 |       17 |     85% |111, 146, 181, 205, 232-239, 361-375, 448, 515 |
| rctab/routers/accounting/send\_emails.py    |      303 |        3 |     99% |534, 741, 897 |
| rctab/routers/accounting/status.py          |       68 |       16 |     76% |36-65, 142 |
| rctab/routers/accounting/subscription.py    |       30 |        0 |    100% |           |
| rctab/routers/accounting/summary\_emails.py |       42 |        3 |     93% |29-30, 102 |
| rctab/routers/accounting/usage.py           |      115 |       15 |     87% |     45-75 |
| rctab/routers/frontend.py                   |      145 |       55 |     62% |53-75, 108-110, 124, 170, 176-183, 208, 281, 352-425 |
| rctab/settings.py                           |       56 |        1 |     98% |       119 |
| rctab/tasks.py                              |       54 |       10 |     81% |60-65, 73-78, 95, 107 |
| rctab/utils.py                              |        5 |        0 |    100% |           |
| **TOTAL**                                   | **1662** |  **212** | **87%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/alan-turing-institute/rctab-api/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/alan-turing-institute/rctab-api/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/alan-turing-institute/rctab-api/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/alan-turing-institute/rctab-api/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Falan-turing-institute%2Frctab-api%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/alan-turing-institute/rctab-api/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.