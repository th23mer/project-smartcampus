# `app/jobs/` — worker et types de jobs

Boucle du worker sur la table générique `job` (`FOR UPDATE SKIP LOCKED`, décision C3) et
types de jobs : `vector_sync`, `email`, `follow_up`, `equivalence_analysis`, `purge`…
(SA-4 §6). Jobs idempotents, reprises avec délai croissant.
