Feature: Test health over time (test-trust plan step 5.1, ADR-0071)

  Scenario: Each slice shows its latest health and how mutation moved
    Given slice "fees" finished ticket "LL-03" with mutation 0.8, CRAP 7, tests 11.7s and 0 flaky runs
    And slice "fees" finished ticket "LL-09" with mutation 0.93, CRAP 9, tests 12.5s and 2 flaky runs
    And slice "loans" finished ticket "LL-01" with mutation 1.0, CRAP 4, tests 9.0s and 0 flaky runs
    When I generate "health" and open the dashboard
    Then the health table contains exactly:
      | Slice | Tickets | Mutation    | Max CRAP | Test run (s) | Flaky |
      | fees  | 2       | 0.80 → 0.93 | 9        | 12.5         | 2     |
      | loans | 1       | 1.00        | 4        | 9.0          | 0     |

  Scenario: The tickets of one slice show its trend
    Given slice "fees" finished ticket "LL-03" with mutation 0.8, CRAP 7, tests 11.7s and 0 flaky runs
    And slice "fees" finished ticket "LL-09" with mutation 0.93, CRAP 9, tests 12.5s and 2 flaky runs
    And slice "loans" finished ticket "LL-01" with mutation 1.0, CRAP 4, tests 9.0s and 0 flaky runs
    When I generate "health" and open the dashboard
    And I show slice "fees"
    Then the health ticket table contains exactly:
      | Ticket | Mutation | Max CRAP | Flaky |
      | LL-03  | 0.80     | 7        | 0     |
      | LL-09  | 0.93     | 9        | 2     |
