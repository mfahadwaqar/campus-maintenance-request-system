Feature: Maintenance request lifecycle
  Residents report faults, Call Center Staff assign them, technicians complete them,
  and the ticket closes automatically. A resident can reopen it for three days.

  Scenario: A resident reports a fault in a valid room
    Given I am logged in as a resident
    When I submit a request for room "A101"
    Then one ticket exists with status "SUBMITTED"
    And the ticket belongs to me

  Scenario: A request for a room that does not exist is refused
    Given I am logged in as a resident
    When I submit a request for room "A999"
    Then I am shown the error "valid room"
    And no ticket exists

  Scenario: Completing a job closes the ticket without any staff action
    Given a ticket that the technician has started
    When the technician completes the job with notes "Replaced the washer"
    Then the ticket status is "CLOSED"
    And the history ends with "COMPLETED" then "CLOSED"

  Scenario: A resident reopens a closed ticket inside the three-day window
    Given a closed ticket that was completed 2 days ago
    When the resident reopens it because "It is dripping again"
    Then the ticket status is "ASSIGNED"
    And the reopen reason is recorded in the history

  Scenario: A resident cannot reopen a closed ticket after the window has passed
    Given a closed ticket that was completed 4 days ago
    When the resident tries to reopen it because "Too late"
    Then the ticket status is "CLOSED"
    And I am told the reopening window has expired

  Scenario: Comments are refused on a closed ticket and allowed again after reopening
    Given a closed ticket that was completed 1 days ago
    When the resident comments "Still leaking"
    Then no comment was saved
    When the resident reopens it because "Leaking again"
    And the resident comments "Thanks for coming back"
    Then one comment was saved

  Scenario: Putting work on hold tells the resident why and until when
    Given a ticket that the technician has started
    When the technician puts the job on hold because "Waiting for a replacement valve"
    Then the ticket status is "ON_HOLD"
    And the resident is notified that the work is on hold

  Scenario: A resident cannot see another resident's ticket
    Given a ticket that belongs to another resident
    And I am logged in as a resident
    When I open that ticket
    Then the page is not found

  Scenario: Staff create and assign a serious fault in one step
    Given I am logged in as call center staff
    When I enter a phone request for the caller and assign it to the unit with priority "URGENT"
    Then one ticket exists with status "ASSIGNED"
    And its priority is "URGENT"

  Scenario Outline: The staff queue finds tickets by room, ticket number and student ID
    Given I am logged in as call center staff
    And two tickets exist in different rooms from different residents
    When I search the queue by <field> "<value>"
    Then the queue lists only the ticket titled "<title>"

    Examples:
      | field       | value           | title        |
      | room        | A2              | In room A205 |
      | room        | a205            | In room A205 |
      | student ID  | st900002        | In room A205 |
      | student ID  | st900001        | In room A101 |
