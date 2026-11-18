Feature: Per-case results and role coverage

  Background:
    Given these graded outcomes in "v3j" on "2026-11-17":
      | case            | outcomes | minutes |
      | synthetic-ll-02 | pass     |         |
    And these graded outcomes in "4a" on "2026-11-18":
      | case               | outcomes       | minutes |
      | synthetic-ll-02    | pass,pass,fail |         |
      | pilot-bk-05g-verify | fail           |         |

  Scenario: Case table
    When I generate "trend" and open the dashboard
    And I select family "4a" on "2026-11-18"
    Then the case table contains exactly:
      | Case               | Kind     | Passes / runs | Majority   |
      | pilot-bk-05g-verify | verifier | 0/1           | Not passed |
      | synthetic-ll-02    | migrator | 2/3           | Passed     |
    When I filter by kind "migrator" and majority "true"
    Then the case table contains exactly:
      | Case            |
      | synthetic-ll-02 |
    When I filter by kind "verifier" and majority "false"
    Then the case table contains exactly:
      | Case               |
      | pilot-bk-05g-verify |

  Scenario: A case's history across families
    When I generate "trend" and open the dashboard
    And I select case "synthetic-ll-02"
    Then the history table contains exactly:
      | Family | Passes / runs |
      | v3j    | 1/1           |
      | 4a     | 2/3           |

  Scenario: Roles with no eval case
    Given returns use roles "afs-migrator, afs-verifier, afs-slice-coordinator"
    And the eval catalog covers "afs-migrator, afs-verifier"
    When I generate "trend" and open the dashboard
    Then the coverage table contains exactly:
      | Role                  | Eval coverage |
      | afs-migrator          | Has case      |
      | afs-slice-coordinator | No case       |
      | afs-verifier          | Has case      |

  Scenario: Folded roles count as their new role
    Given returns use roles "afs-specialist-migrator"
    And the eval catalog covers "afs-migrator"
    And the harness records "afs-specialist-migrator" as folded into "afs-migrator"
    When I generate "trend" and open the dashboard
    Then the coverage table contains exactly:
      | Role         | Eval coverage |
      | afs-migrator | Has case      |
