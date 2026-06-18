Feature: Book a consultation slot
  As a prospective client
  I want to book a consultation slot
  So that I can get expert advice on my architecture

  Background:
    Given the booking service is running
    And the availability index is initialised with no existing bookings

  Scenario: Successfully book an available slot
    Given a valid booking payload for date "2099-06-15" at "09:00"
    When I POST the booking to "/v1/bookings"
    Then the response status is 201
    And the response contains a booking id
    And the booking has status "confirmed"
    And the slot "09:00" on "2099-06-15" is no longer available

  Scenario: Booking a taken slot returns conflict
    Given a valid booking payload for date "2099-06-16" at "10:00"
    And that slot is already booked
    When I POST the booking to "/v1/bookings"
    Then the response status is 409
    And the error code is "SLOT_UNAVAILABLE"

  Scenario: Booking with invalid email is rejected
    Given a booking payload with email "not-an-email"
    When I POST the booking to "/v1/bookings"
    Then the response status is 422

  Scenario: Booking with missing required field is rejected
    Given a booking payload missing the "details" field
    When I POST the booking to "/v1/bookings"
    Then the response status is 422

  Scenario: Booking with details too short is rejected
    Given a booking payload with details "short"
    When I POST the booking to "/v1/bookings"
    Then the response status is 422
