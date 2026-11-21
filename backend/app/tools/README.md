# `app/tools/` — outils exposés aux agents (E4, logique E2/E3)

Enveloppes typées des services (`get_fees`, `check_eligibility`, `list_free_slots`…), avec le
contexte de l'appelant (`CurrentUser`) : un agent n'a jamais plus de droits que l'utilisateur
qu'il sert. Erreurs structurées au format `AppError` (ex. `ACADEMIC_YEAR_REQUIRED`).
**À remplir par E4.**
