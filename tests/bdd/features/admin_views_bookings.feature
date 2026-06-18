Feature: Admin views all bookings
  As an admin
  I want to view all bookings
  So that I can manage my consultation schedule

  Background:
    Given the booking service is running

  Scenario: Admin can list all bookings
    Given 3 bookings exist in the system
    When an admin GETs "/v1/bookings"
    Then the response status is 200
    And the response contains 3 bookings

  Scenario: Non-admin cannot list bookings
    When a regular user GETs "/v1/bookings"
    Then the response status is 403

  Scenario: Unauthenticated user cannot list bookings
    When an unauthenticated user GETs "/v1/bookings"
    Then the response status is 401

  Scenario: Admin can get a single booking by ID
    Given an existing booking for date "2099-08-01" at "09:30"
    When an admin GETs the booking by id
    Then the response status is 200
    And the booking date is "2099-08-01"
    And the booking time is "09:30"

  Scenario: Getting a non-existent booking returns 404
    When anyone GETs booking id "deadbeef-0000-0000-0000-000000000000"
    Then the response status is 404
    And the error code is "NOT_FOUND"
