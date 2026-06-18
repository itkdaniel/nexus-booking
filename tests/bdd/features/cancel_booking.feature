Feature: Cancel a booking
  As an admin
  I want to cancel an existing booking
  So that the time slot becomes available again

  Background:
    Given the booking service is running
    And the availability index is initialised with no existing bookings

  Scenario: Admin cancels a booking and slot is freed
    Given an existing booking for date "2099-07-07" at "13:00"
    When an admin PATCHes the booking with cancelled=true
    Then the response status is 200
    And the booking has cancelled=true
    And the slot "13:00" on "2099-07-07" is available again

  Scenario: Non-admin cannot cancel a booking
    Given an existing booking for date "2099-07-08" at "14:00"
    When a regular user PATCHes the booking with cancelled=true
    Then the response status is 403

  Scenario: Cancelling a non-existent booking returns 404
    When an admin PATCHes booking id "non-existent-id" with cancelled=true
    Then the response status is 404
    And the error code is "NOT_FOUND"

  Scenario: Admin deletes a booking
    Given an existing booking for date "2099-07-09" at "15:00"
    When an admin DELETEs the booking
    Then the response status is 204
