Feature: How the eval has moved

  Scenario: Runs are grouped into families
    Given the graded family "v3j" on "2026-11-17" has 3 runs and a state file
    When I generate "trend" and open the dashboard
    Then the family table contains exactly:
      | Date       | Family | Runs |
      | 2026-11-17 | v3j    | 3    |

  Scenario: A case passes a family by majority
    Given these graded outcomes in "v3j" on "2026-11-17":
      | case               | outcomes   | minutes |
      | pilot-bk-05g-verify | pass,pass,fail |        |
      | synthetic-ll-02    | pass,fail      |        |
    When I generate "trend" and open the dashboard
    Then the case table contains exactly:
      | Case               | Passes / runs | Majority   |
      | pilot-bk-05g-verify | 2/3           | Passed     |
      | synthetic-ll-02    | 1/2           | Not passed |

  Scenario: Pass rate is split by kind
    Given these graded outcomes in "v3j" on "2026-11-17":
      | case     | outcomes | minutes |
      | a-verify | pass     |         |
      | b        | fail     |         |
      | c        | pass     |         |
    When I generate "trend" and open the dashboard
    Then the family table contains exactly:
      | Verifier | Migrator | Pass rate |
      | 1/1      | 1/2      | 0.667     |

  Scenario: Cost per family
    Given these graded outcomes in "v3j" on "2026-11-17":
      | case | outcomes | minutes |
      | a    | pass     | 10      |
      | b    | pass     | 7       |
      | c    | pass     | 60      |
      | d    | pass     |         |
    And the graded family "4a" on "2026-11-18" has 1 runs and a state file
    When I generate "trend" and open the dashboard
    Then the family table contains exactly:
      | Family | Median min/case |
      | v3j    | 10              |
      | 4a     |                 |

  Scenario: Trend chart
    Given the graded family "4a" on "2026-11-18" has 1 runs and a state file
    And the graded family "v3j" on "2026-11-17" has 3 runs and a state file
    When I generate "trend" and open the dashboard
    Then the trend chart plots "v3j, 4a" in that order
    When I hover the "v3j" point
    Then "chart" says "v3j · 2026-11-17 · 3 run(s) · 1/1 cases passed"
