Feature: What waits on the operator

  Scenario Outline: Workflow runs waiting for approval are grouped by branch
    Given 3 workflow runs on "copilot/ll-06" in "ai-factory-synthetic-target" have waited 1, 3 and 2 days
    And the branch has <attachment>
    When I generate "needs" and open the dashboard
    Then Needs shows one "Approve workflow runs" row titled "3 run(s) on copilot/ll-06"
    And the row shows "3.0 d" and links to "https://github.com/martins-vds/ai-factory-synthetic-target/<destination>"

    Examples:
      | attachment | destination |
      | a PR       | pull/42     |
      | no PR      | actions     |

  Scenario: A ready pull request is a merge need
    Given "ai-factory-swarm" has an open ready PR 202
    When I generate "needs" and open the dashboard
    Then Needs shows one "Merge pull request" row titled "PR #202"
    And the row links to "https://github.com/martins-vds/ai-factory-swarm/pull/202"

  Scenario: A draft pull request is not a merge need
    Given "ai-factory-pilot-target" has an open draft PR 173
    When I generate "needs" and open the dashboard
    Then Needs has no "Merge pull request" rows

  Scenario: A slice acceptance waiting for the side-by-side check
    Given "ai-factory-pilot-target" has an open draft PR 173
    And its changed ".afs-slice-coordinator.yaml" at the PR head says "human_check: requested"
    When I generate "needs" and open the dashboard
    Then Needs shows one "Side-by-side check" row titled "PR #173"
    And the row links to "https://github.com/martins-vds/ai-factory-pilot-target/pull/173"
    And the canvas has no GitHub write controls or endpoints

  Scenario: Oldest needs come first
    Given ready PRs have these waiting ages:
      | PR  | days |
      | 201 | 1.24 |
      | 202 | 3.19 |
      | 203 | 2.12 |
    When I generate "needs" and open the dashboard
    Then Needs shows the items in order "PR #202, PR #203, PR #201"
    And their waiting times are "3.2 d, 2.1 d, 1.2 d"

  Scenario: Nothing waits
    When I generate "needs" and open the dashboard
    Then "needs-data" says "Nothing waits on the operator."
