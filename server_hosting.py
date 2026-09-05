import sys
import shutil
import subprocess
from pathlib import Path

def clean_clone_setup_and_run(repo_url: str, target_dir: str, token_key: str, token_value: str, branch: str = "main"):
    """Deletes the target directory if it exists, initializes it fresh, adds token, and runs main.py."""
    folder = Path(target_dir).resolve()
    
    if folder.exists():
        print(f"Directory '{folder}' already exists. Deleting it for a clean setup...")
        try:
            # shutil.rmtree removes the directory and all files/folders inside it
            shutil.rmtree(folder)
            print("Successfully deleted old directory.")
        except Exception as e:
            print(f"Error while deleting directory: {e}")
            return

    # Create a fresh, empty directory
    folder.mkdir(parents=True, exist_ok=True)

    try:
        print("Initializing blank local repository...")
        subprocess.run(["git", "init"], cwd=folder, check=True, capture_output=True)

        print(f"Linking remote origin: {repo_url}")
        subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=folder, check=True, capture_output=True)

        print(f"Pulling files from branch '{branch}'...")
        subprocess.run(["git", "pull", "origin", branch], cwd=folder, check=True, capture_output=True)
        print("Git repository pulled successfully!")

        env_path = folder / ".env"
        env_path.write_text(f"{token_key}={token_value}\n")
        print(f"Successfully saved {token_key} to {env_path.name}")

        main_script_path = folder / "main.py"
        if main_script_path.exists():
            print(f"Launching {main_script_path.name}...")
            subprocess.run([sys.executable, str(main_script_path)], cwd=folder, check=True)
        else:
            print(f"Error: Could not find '{main_script_path.name}' in the repository.")

    except subprocess.CalledProcessError as e:
        print("An error occurred during execution:")
        print(e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr)

# Configuration
github_url = "https://github.com/asabljic-iit/flip7-discord-bot.git"
target_folder = "./flip7-discord-bot"
bot_token = "token_here" # Replace with your token

# Run the automation
clean_clone_setup_and_run(
    repo_url=github_url,
    target_dir=target_folder,
    token_key="DISCORD_TOKEN",
    token_value=bot_token,
    branch="main"
)
