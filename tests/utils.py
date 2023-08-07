"""Test helper classes."""
from typing import Any, List


def print_list_diff(expected: List[Any], actual: List[Any]) -> None:
    print("")
    for i, call in enumerate(expected):
        print("expected:", call)
        if i < len(actual):
            print("actual:  ", actual[i])
