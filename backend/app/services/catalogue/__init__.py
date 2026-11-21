"""Services du catalogue (E2) : noyau partagé de publication (SA-21) et domaines.

- `tx` : transaction staff (`SET LOCAL app.current_user_id`) et traduction des erreurs SQL ;
- `publication` : workflow draft → pending_review → published → archived (4 yeux, D-B/D-H),
  lecture « publié et valide à la date D », ETag, carte source ;
- `fees`, `admission` (SA-21) ; `programmes`, `curricula` (SA-20).
"""
