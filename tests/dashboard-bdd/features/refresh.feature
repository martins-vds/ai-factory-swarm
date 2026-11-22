Feature: Fresh data under the viewer's own identity

  Scenario: Generate with the runner's credentials
    Given the runner is signed in to the GitHub CLI
    When I generate "needs", "sessions" and "trend"
    Then the GitHub reads used the runner's credentials
    When the runner cannot read "ai-factory-synthetic-target"
    Then "needs" and "sessions" generation fail with that repository's gh error

  Scenario: Every table shows when it was generated
    Given all datasets were generated 4 minutes ago
    When I open the dashboard
    Then every dataset shows its Generated time and no stale datasets
    When all datasets were generated 6 minutes ago
    And I wait for the next poll
    Then only "sessions" is stale
    When all datasets were generated 61 minutes ago
    And I wait for the next poll
    Then only "sessions, needs, families, cases, coverage, health, healthTickets" is stale

  Scenario: The data can be checked and rerun
    When I generate "needs" and open the dashboard
    And I open the "needs" generator details
    Then the details show the generator source and the command that actually ran

  Scenario: The dashboard takes no actions
    Given "ai-factory-swarm" has an open ready PR 202
    And eval issue 1342 is assigned to Copilot and has WIP PR 1350 started 52 minutes ago
    When I generate "needs" and "sessions" and open the dashboard
    Then the canvas has no GitHub write controls or endpoints
