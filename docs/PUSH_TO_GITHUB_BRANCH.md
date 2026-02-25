# Push this update to a new Git branch (GitHub)

This guide helps you publish the updated bot to a **new branch** in your repo:

- Repo: https://github.com/sqwhh/fic-grade-bot

> Tip: **Do not commit `.env` or any `.db` files**. Keep secrets local.

---

## 0) Prerequisites

- Git installed
- You are in the project folder (the one that contains `README.md`, `Dockerfile`, `docker-compose.yml`)

---

## 1) Make sure your local repo is clean

```bash
git status
```

If you see unwanted files (like `.env`, `data/`, `*.db`), make sure they are ignored and not staged:

```bash
git restore --staged . || true
```

---

## 2) Update `main` and create a new branch

```bash
git checkout main
git pull origin main

git checkout -b feature/moodle-courses-ui
```

(You can name the branch however you want, e.g. `moodle-v1`.)

---

## 3) Copy/merge the updated project files

If you downloaded a zip of the updated project:

1. Unzip it somewhere
2. Copy the contents into your repo folder **overwriting existing files**

Then verify:

```bash
git status
```

---

## 4) Add + commit

```bash
git add .

git commit -m "Add Moodle course gradebook + improved UI"
```

---

## 5) Push the branch to GitHub

```bash
git push -u origin feature/moodle-courses-ui
```

---

## 6) Open a Pull Request

1. Go to your repo on GitHub
2. GitHub will show a banner: **Compare & pull request** → click it
3. Create the PR into `main`

---

## 7) (Optional) Update your server (Docker)

On the server:

```bash
cd /path/to/fic-grade-bot

git fetch origin

git checkout feature/moodle-courses-ui

docker compose up -d --build
```

Your `.env` and the Docker volume with the DB will stay intact.
