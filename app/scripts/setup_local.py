import subprocess
import webbrowser


if __name__ == "__main__":
    subprocess.Popen(["python", "-m", "candyconc.entrypoints.cli"])
    webbrowser.open("http://127.0.0.1:8550")
