Feature: Active remote sessions

  Scenario: A running session is listed
    Given eval issue 1342 is assigned to Copilot and has WIP PR 1350 started 4 minutes ago
    When the dashboard polls GitHub through the local generator
    Then the active sessions table contains exactly:
      | Repository      | Issue | PR    | Agent        | Base                               | Ticket | Status  |
      | ai-factory-eval | #1342 | #1350 | afs-migrator | eval/2026-11-18-4ra-r1/synthetic-ll-02 | LL-02 | running |
    And PR 1350 links to "https://github.com/martins-vds/ai-factory-eval/pull/1350"

  Scenario Outline: Elapsed time against the session limit
    Given eval issue 1342 is assigned to Copilot and has WIP PR 1350 started <elapsed> minutes ago
    And the PR head commit is <commit> minutes old
    When I generate "sessions" and open the dashboard
    Then the active sessions table contains exactly:
      | Elapsed             | Status   |
      | <elapsed> min of 60 | <status> |

    Examples:
      | elapsed | commit | status     |
      | 49      | 20     | running    |
      | 50      | 20     | near limit |
      | 52      | 20     | near limit |
      | 60      | 20     | near limit |
      | 61      | 9      | near limit |
      | 61      | 10     | over limit |

  Scenario: Session start time
    Given eval issue 1342 is assigned to Copilot and has WIP PR 1350 started 52 minutes ago
    And its first assignment was 55 minutes ago
    When I generate "sessions" and open the dashboard
    Then "active" says "52 min of 60"
    When Copilot is reassigned 7 minutes ago
    And I regenerate "sessions" and wait for the next poll
    Then "active" says "7 min of 60"

  Scenario: Eval sessions show their run and case
    Given eval issue 1342 is assigned to Copilot and has WIP PR 1350 started 52 minutes ago
    And eval issue 1343 is assigned to Copilot and has WIP PR 1351 started 40 minutes ago
    And PR 1351 dropped "[WIP]" 5 minutes ago
    When I generate "sessions" and open the dashboard
    And I group sessions by run
    Then the active sessions table contains exactly:
      | Eval run / case                    |
      | 2026-11-18-4ra-r1 synthetic-ll-02 |
    And the run summary table contains exactly:
      | Eval run      | Running | Finished (24h) |
      | 2026-11-18-4ra-r1 | 1    | 1             |

  Scenario: A session finishes
    Given eval issue 1342 is assigned to Copilot and has WIP PR 1350 started 52 minutes ago
    When I generate "sessions" and open the dashboard
    Then "active" says "#1350"
    When PR 1350 dropped "[WIP]" 5 minutes ago
    And I regenerate "sessions" and wait for the next poll
    Then "active" says "No sessions are running."
    And the finished sessions table contains exactly:
      | PR    | Duration | Status   |
      | #1350 | 47 min   | finished |

  Scenario Outline: A session is assigned but has no PR yet
    Given eval issue 1342 was assigned to Copilot <minutes> minutes ago with no PR
    When I generate "sessions" and open the dashboard
    Then the active sessions table contains exactly:
      | Issue | PR | Status   |
      | #1342 | —  | <status> |
    And there is no PR link in the active sessions table

    Examples:
      | minutes | status   |
      | 4       | starting |
      | 15      | no PR    |

  Scenario: A session's checks need approval
    Given eval issue 1342 is assigned to Copilot and has WIP PR 1350 started 52 minutes ago
    And its workflow runs need approval
    When I generate "needs" and "sessions" and open the dashboard
    And I follow the session's "Runs need approval" link
    Then the targeted Needs row shows "Approve workflow runs" for PR 1350
    And the canvas has no GitHub write controls or endpoints

  Scenario: Summary counts
    Given eval issue 1342 is assigned to Copilot and has WIP PR 1350 started 52 minutes ago
    And eval issue 1343 is assigned to Copilot and has WIP PR 1351 started 61 minutes ago
    When I generate "sessions" and open the dashboard
    Then the header shows 2 active, 1 near limit and 1 stalled

  Scenario: No active sessions
    When I generate "sessions" and open the dashboard
    Then "active" says "No sessions are running."
