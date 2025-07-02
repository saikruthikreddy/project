# 3. core/project_service.py (Database Service)
# ================================
import pandas as pd
import os

def get_projects_for_user(user_id):
    """
    Fetch all projects for a specific user from CSV database
    """
    try:
        # Check if file exists
        csv_path = "datastores/dummy_db_user_projects.csv"
        if not os.path.exists(csv_path):
            print(f"Warning: CSV file not found at {csv_path}")
            return []
            
        df = pd.read_csv(csv_path)
        matched = df[df["userID"] == user_id]
        projects = matched[["projectID", "projectName"]].to_dict(orient="records")
        return projects
        
    except Exception as e:
        print(f"Error in get_projects_for_user: {str(e)}")
        return []

def get_project_purpose(project_id):
    """
    Fetch project purpose for a specific project ID from CSV database
    """
    try:
        # Check if file exists
        csv_path = "datastores/dummy_db_ProjectPurpose.csv"
        if not os.path.exists(csv_path):
            print(f"Warning: CSV file not found at {csv_path}")
            return "No specific project purpose found."
            
        df = pd.read_csv(csv_path)
        match = df[df["projectID"] == project_id]
        
        if not match.empty:
            return match.iloc[0]["projectPurpose"]
        else:
            return "No specific project purpose found."
            
    except Exception as e:
        print(f"Error in get_project_purpose: {str(e)}")
        return f"Error retrieving project purpose: {str(e)}"
