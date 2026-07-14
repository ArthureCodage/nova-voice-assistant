from __future__ import annotations

import json
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
WORKSPACE_DIR = ROOT / "workspace"
SCRIPTS_DIR = ROOT / "scripts"
CONFIG_PATH = ROOT / "config.json"
PERSONA_PATH = ROOT / "persona.md"
DB_PATH = DATA_DIR / "assistant.db"


def load_config() -> dict:
    defaults = {
        "assistant_name": "Nova",
        "speak_responses": True,
        "history_turns": 8,
        "speech_timeout_seconds": 20,
        "whisper_model": "base",
        "microphone_threshold": 0.015,
        "piper_voice": "fr_FR-siwis-medium",
        "piper_speed": 1.08,
    }
    if CONFIG_PATH.exists():
        defaults.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    return defaults


class Memory:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def remember(self, content: str) -> int:
        cursor = self.connection.execute(
            "INSERT INTO memories(content, created_at) VALUES (?, ?)",
            (content.strip(), self.now()),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def forget(self, memory_id: int) -> bool:
        cursor = self.connection.execute(
            "DELETE FROM memories WHERE id = ?", (memory_id,)
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def memories(self) -> list[tuple[int, str]]:
        return list(
            self.connection.execute(
                "SELECT id, content FROM memories ORDER BY id ASC"
            )
        )

    def add_turn(self, role: str, content: str) -> None:
        self.connection.execute(
            "INSERT INTO turns(role, content, created_at) VALUES (?, ?, ?)",
            (role, content.strip(), self.now()),
        )
        self.connection.commit()

    def recent_turns(self, limit: int) -> list[tuple[str, str]]:
        rows = self.connection.execute(
            "SELECT role, content FROM turns ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return list(reversed(rows))

    def clear_history(self) -> None:
        self.connection.execute("DELETE FROM turns")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


class WindowsVoice:
    def __init__(
        self,
        timeout_seconds: int,
        whisper_model: str,
        threshold: float,
        piper_voice: str,
        piper_speed: float,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.whisper_model = whisper_model
        self.threshold = threshold
        self.piper_voice = piper_voice
        self.piper_speed = piper_speed
        self._whisper = None
        self._piper = None

    @staticmethod
    def _powershell(script: Path, args: list[str] | None = None, text: str = "") -> str:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *(args or []),
        ]
        result = subprocess.run(
            command,
            input=text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(detail or "Erreur du service vocal Windows")
        return result.stdout.strip()

    def listen(self) -> str:
        try:
            return self._powershell(
                SCRIPTS_DIR / "listen.ps1",
                ["-TimeoutSeconds", str(self.timeout_seconds)],
            )
        except RuntimeError as windows_error:
            try:
                return self._listen_with_whisper()
            except ImportError as error:
                raise RuntimeError(
                    "Aucun moteur vocal Windows n'est installé et Faster-Whisper est absent. "
                    "Lance setup.cmd une fois."
                ) from error
            except Exception as whisper_error:
                raise RuntimeError(
                    f"Reconnaissance Windows indisponible ({windows_error}); "
                    f"échec de Whisper ({whisper_error})."
                ) from whisper_error

    def _listen_with_whisper(self) -> str:
        import numpy as np
        import sounddevice as sd
        from faster_whisper import WhisperModel

        if self._whisper is None:
            print(f"Chargement du modèle vocal local '{self.whisper_model}'…")
            self._whisper = WhisperModel(
                self.whisper_model,
                device="cpu",
                compute_type="int8",
            )

        sample_rate = 16000
        block_seconds = 0.1
        block_size = int(sample_rate * block_seconds)
        silence_seconds = 1.1
        audio_queue: queue.Queue = queue.Queue()
        pre_roll: deque = deque(maxlen=5)
        frames: list = []
        speech_started = False
        last_voice = time.monotonic()
        started_at = time.monotonic()

        def callback(indata, frame_count, timing, status) -> None:
            del frame_count, timing
            if status:
                print(f"Avertissement micro : {status}")
            audio_queue.put(indata.copy())

        print("Parle maintenant; l'enregistrement s'arrête après une seconde de silence.")
        with sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=block_size,
            callback=callback,
        ):
            while time.monotonic() - started_at < self.timeout_seconds:
                block = audio_queue.get(timeout=2)
                level = float(np.sqrt(np.mean(np.square(block))))
                if not speech_started:
                    pre_roll.append(block)
                if level >= self.threshold:
                    if not speech_started:
                        frames.extend(pre_roll)
                        speech_started = True
                    last_voice = time.monotonic()
                if speech_started:
                    frames.append(block)
                    if time.monotonic() - last_voice >= silence_seconds:
                        break

        if not frames:
            return ""
        audio = np.concatenate(frames, axis=0).reshape(-1)
        segments, _ = self._whisper.transcribe(
            audio,
            language="fr",
            vad_filter=True,
            beam_size=3,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def speak(self, text: str) -> None:
        spoken_text = self._clean_for_speech(text)
        try:
            self._speak_with_piper(spoken_text)
        except Exception as piper_error:
            print(f"(Voix française indisponible, repli sur Windows : {piper_error})")
            self._powershell(SCRIPTS_DIR / "speak.ps1", text=spoken_text)

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
        text = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"[*_`#>]", "", text)
        return re.sub(r"\s+", " ", text).strip()

    def _speak_with_piper(self, text: str) -> None:
        import sounddevice as sd
        from piper import PiperVoice, SynthesisConfig

        model_path = ROOT / "models" / f"{self.piper_voice}.onnx"
        if not model_path.exists():
            raise FileNotFoundError(f"modèle absent : {model_path.name}")
        if self._piper is None:
            self._piper = PiperVoice.load(model_path)

        synthesis = self._piper.synthesize(
            text,
            syn_config=SynthesisConfig(
                length_scale=self.piper_speed,
                noise_scale=0.62,
                noise_w_scale=0.72,
                normalize_audio=True,
                volume=0.92,
            ),
        )
        first = next(iter(synthesis), None)
        if first is None:
            return
        with sd.RawOutputStream(
            samplerate=first.sample_rate,
            channels=first.sample_channels,
            dtype="int16",
        ) as output:
            output.write(first.audio_int16_bytes)
            for chunk in synthesis:
                output.write(chunk.audio_int16_bytes)

    def capture_screen(self, destination: Path) -> None:
        self._powershell(
            SCRIPTS_DIR / "capture-screen.ps1",
            ["-Destination", str(destination)],
        )


class CodexBrain:
    def __init__(self, memory: Memory, config: dict) -> None:
        self.memory = memory
        self.config = config
        self.codex = shutil.which("codex.cmd") or shutil.which("codex")
        if not self.codex:
            raise RuntimeError("Codex CLI est introuvable dans PATH.")

    def build_prompt(self, user_text: str, screen_attached: bool = False) -> str:
        persona = PERSONA_PATH.read_text(encoding="utf-8").strip()
        facts = self.memory.memories()
        turns = self.memory.recent_turns(int(self.config["history_turns"]) * 2)
        memory_text = "\n".join(f"- [{mid}] {text}" for mid, text in facts) or "- Aucune"
        history_text = "\n".join(f"{role}: {text}" for role, text in turns) or "Aucun"
        screen_rule = (
            "Une capture d'écran vient d'être jointe. Décris seulement ce qui est visible "
            "et signale clairement toute incertitude."
            if screen_attached
            else "Aucune capture d'écran n'est jointe. Ne prétends pas voir l'écran."
        )
        return f"""
Tu es l'assistant personnel vocal local de l'utilisateur. Réponds toujours en français,
de façon naturelle et concise, sauf demande contraire.

PERSONNALITÉ
{persona}

RÈGLES DE SÉCURITÉ
- Tu es ici en mode discussion en lecture seule.
- Ne lance aucune commande et ne modifie aucun fichier.
- N'affirme jamais avoir effectué une action sur le PC.
- Si une action est demandée, explique brièvement ce que tu proposes et dis qu'elle
  nécessitera le futur mode Action avec confirmation.
- Ne révèle pas de raisonnement interne; donne seulement la réponse utile.
- {screen_rule}

MÉMOIRES EXPLICITEMENT APPROUVÉES
{memory_text}

CONVERSATION RÉCENTE
{history_text}

MESSAGE ACTUEL DE L'UTILISATEUR
{user_text}
""".strip()

    def ask(self, user_text: str, image: Path | None = None) -> str:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        fd, output_name = tempfile.mkstemp(prefix="codex-response-", suffix=".txt", dir=DATA_DIR)
        os.close(fd)
        output_path = Path(output_name)
        prompt = self.build_prompt(user_text, screen_attached=image is not None)
        command = [
            self.codex,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--cd",
            str(WORKSPACE_DIR),
            "--output-last-message",
            str(output_path),
        ]
        if image is not None:
            command.extend(["--image", str(image)])
        command.append("-")
        try:
            result = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=240,
                check=False,
            )
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip()
                raise RuntimeError(detail or "Codex n'a pas pu répondre.")
            answer = output_path.read_text(encoding="utf-8").strip()
            if not answer:
                raise RuntimeError("Codex a retourné une réponse vide.")
            return answer
        finally:
            output_path.unlink(missing_ok=True)


def print_help() -> None:
    print(
        """
Commandes :
  Entrée vide          parler au microphone
  /screen [question]   capturer et expliquer l'écran
  /remember TEXTE      enregistrer une mémoire approuvée
  /memories            afficher les mémoires
  /forget ID           supprimer une mémoire
  /clear                effacer l'historique de conversation
  /mute | /unmute      désactiver/réactiver la réponse vocale
  /help                 afficher cette aide
  /quit                 quitter
""".strip()
    )


def main() -> int:
    if os.name != "nt":
        print("Ce prototype vocal utilise les services audio de Windows.", file=sys.stderr)
        return 1

    config = load_config()
    memory = Memory(DB_PATH)
    voice = WindowsVoice(
        int(config["speech_timeout_seconds"]),
        str(config["whisper_model"]),
        float(config["microphone_threshold"]),
        str(config["piper_voice"]),
        float(config["piper_speed"]),
    )
    try:
        brain = CodexBrain(memory, config)
    except RuntimeError as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1

    speaking = bool(config["speak_responses"])
    name = str(config["assistant_name"])
    print(f"{name} est prêt. Écris un message ou appuie sur Entrée pour parler.")
    print("Tape /help pour les commandes. Mode actuel : discussion en lecture seule.")

    while True:
        try:
            raw = input("\nToi > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nÀ bientôt.")
            break

        if raw.lower() in {"/quit", "/exit"}:
            print("À bientôt.")
            break
        if raw.lower() == "/help":
            print_help()
            continue
        if raw.lower() == "/memories":
            items = memory.memories()
            print("\n".join(f"[{mid}] {text}" for mid, text in items) or "Aucune mémoire.")
            continue
        if raw.lower().startswith("/remember "):
            content = raw[len("/remember ") :].strip()
            if content:
                print(f"Mémoire enregistrée avec l'identifiant {memory.remember(content)}.")
            continue
        if raw.lower().startswith("/forget "):
            try:
                memory_id = int(raw.split(maxsplit=1)[1])
                print("Mémoire supprimée." if memory.forget(memory_id) else "Mémoire introuvable.")
            except ValueError:
                print("Utilise /forget suivi d'un nombre.")
            continue
        if raw.lower() == "/clear":
            memory.clear_history()
            print("Historique effacé. Les mémoires explicites sont conservées.")
            continue
        if raw.lower() == "/mute":
            speaking = False
            print("Voix désactivée.")
            continue
        if raw.lower() == "/unmute":
            speaking = True
            print("Voix activée.")
            continue

        image: Path | None = None
        if raw.lower().startswith("/screen"):
            question = raw[len("/screen") :].strip() or "Explique-moi ce qui est affiché à l'écran."
            image = DATA_DIR / "latest-screen.png"
            try:
                voice.capture_screen(image)
                raw = question
                print("Capture effectuée localement et envoyée à Codex pour cette réponse.")
            except Exception as error:
                print(f"Impossible de capturer l'écran : {error}")
                continue
        elif not raw:
            print("Je t'écoute…")
            try:
                raw = voice.listen().strip()
            except Exception as error:
                print(f"Microphone indisponible : {error}")
                continue
            if not raw:
                print("Je n'ai rien entendu.")
                continue
            print(f"Reconnu : {raw}")

        memory.add_turn("Utilisateur", raw)
        try:
            answer = brain.ask(raw, image=image)
        except Exception as error:
            print(f"Codex indisponible : {error}")
            continue
        finally:
            if image is not None:
                image.unlink(missing_ok=True)

        memory.add_turn(name, answer)
        print(f"\n{name} > {answer}")
        if speaking:
            try:
                voice.speak(answer)
            except Exception as error:
                print(f"(Réponse vocale indisponible : {error})")

    memory.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
