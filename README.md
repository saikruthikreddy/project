giani_pkb/
│
├── __init__.py
│
├── api/                                 🟩 NEW — Routes/controllers
│   └── ppt_addin_controller.py          # Endpoints for suggest-titles, list-projects
│
├── core/                                🟦 Existing shared logic
│   ├── __init__.py
│   ├── classification_service.py
│   ├── metadata_manager.py
│   ├── models.py
│   ├── summarization_service.py
│   │
│   ├── ppt_title_service.py             🟩 NEW — Handles title generation via Gemini
│   └── project_service.py               🟩 NEW — Returns projectPurpose / project list
│
├── preprocessing/                       🟦 Parsers (unchanged)
│   ├── CSV.py
│   ├── Docx.py
│   ├── Images.py
│   ├── PPTX.py
│   ├── Processing.py
│   ├── Text.py
│   └── __init__.py
│
├── prompts/                             🟦 Existing prompts
│   ├── __init__.py
│   ├── csv_analysis_prompt.txt
│   ├── file_classification_prompt.txt
│   ├── summarization_group_a_prompt.txt
│   ├── summarization_group_b_prompt.txt
│   ├── summarization_group_c_prompt.txt
│   └── summarization_group_d_prompt.txt
│
├── prompts/ppt/                         🟩 NEW — Prompt templates for PPT feature
│   ├── title_generation_prompt.txt      # For generating new titles
│   └── title_refine_prompt.txt          # For refining a specific title
│
├── datastores/                          🟩 NEW — Simulated database CSVs
│   ├── dummy_db_projectpurpose.csv      # Maps projectID → projectPurpose
│   └── dummy_db_user_projects.csv       # Maps userID → list of projects
│
├── ui/                                  🟦 Existing UI layer (unchanged)
│   ├── __init__.py
│   ├── file_upload_app.py
│   └── summarization_app.py
│
├── utils/                               🟦 Existing utils (unchanged)
│   ├── __init__.py
│   ├── config.py
│   ├── constants.py
│   ├── exceptions.py
│   └── prompt_loader.py
│
├── config/                              🟩 Moved or added secrets support
│   ├── secrets.env                      # Stores GEMINI_API_KEY securely
│
├── main_ppt_addin.py                    🟩 NEW — Flask app entry point for PPT backend
├── requirements.txt
└── README.md


📋 POST /projects/list-by-user
Returns all projectID + projectName pairs for a given user.

✅ Request JSON

{
  "userID": "user_123"
}

✅ Response JSON

{
  "projects": [
    {
      "projectID": "proj001",
      "projectName": "AI Slide Automation"
    },
    {
      "projectID": "proj002",
      "projectName": "Marketing Pitch Deck"
    }
  ]
}
