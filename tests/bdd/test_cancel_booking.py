"""
BDD scenario runner for: Cancel a booking.
Imports step definitions from steps/ and registers all scenarios in the feature file.
"""
import pytest
from pytest_bdd import scenarios

from tests.bdd.steps.booking_steps import *  # noqa: F401,F403

scenarios("features/cancel_booking.feature")
