"""BTC Monitor — Load & Stress Test Suite.
Simulates 200-500 concurrent users in 3 waves.

Usage:
  locust -f tests/locustfile.py --host https://btc.smartmarkettoday.com
  locust -f tests/locustfile.py --host http://localhost:8000 --headless -u 200 -r 20 --run-time 5m
"""
import random, json, time
from locust import HttpUser, task, between, constant

QUESTION_POOL = [
    "Что с рынком?",
    "Прогноз BTC на сегодня",
    "Стоит ли покупать?",
    "Анализ индикаторов",
    "Уровни поддержки и сопротивления",
    "Что такое MVRV?",
    "Когда дно?",
    "Какой тренд?",
    "Оцени волатильность",
    "Сравни BTC с S&P500",
]

class MiniAppUser(HttpUser):
    """Волна A: открывают Mini App, смотрят графики/дашборд."""
    wait_time = between(0.5, 2.0)

    @task(20)
    def dashboard(self):
        self.client.get("/miniapp/dashboard", name="[A] Dashboard")

    @task(15)
    def chart(self):
        tf = random.choice(["1h", "4h", "1d"])
        self.client.get(f"/miniapp/chart?timeframe={tf}&limit=50", name="[A] Chart")

    @task(10)
    def indicators(self):
        self.client.get("/btc/indicators", name="[A] Indicators")

    @task(10)
    def predict(self):
        self.client.get("/miniapp/predict", name="[A] Predict")

    @task(8)
    def fear_greed(self):
        self.client.get("/miniapp/fear-greed", name="[A] FearGreed")

    @task(8)
    def news(self):
        self.client.get("/miniapp/news", name="[A] News")

    @task(5)
    def volatility(self):
        self.client.get("/miniapp/volatility", name="[A] Volatility")

    @task(3)
    def metcalfe(self):
        self.client.get("/miniapp/metcalfe", name="[A] Metcalfe")

    @task(2)
    def consensus(self):
        self.client.get("/miniapp/consensus", name="[A] Consensus")

    @task(1)
    def lessons(self):
        self.client.get("/miniapp/lessons", name="[A] Lessons")


class GameUser(HttpUser):
    """Волна B: играют, отправляют POST на сохранение очков."""
    wait_time = between(0.3, 1.0)

    def on_start(self):
        self.user_id = random.randint(1000000, 9999999)

    @task(30)
    def mining_click(self):
        self.client.post("/miniapp/game/mining/click", json={},
                         name="[B] Mining click",
                         headers={"X-Test-User": str(self.user_id)})

    @task(20)
    def mining_state(self):
        self.client.get("/miniapp/game/mining/state", name="[B] Mining state")

    @task(15)
    def roulette_spin(self):
        bet = random.randint(1, 5)
        self.client.post("/miniapp/game/roulette",
                         json={"bet": bet},
                         name="[B] Roulette spin",
                         headers={"X-Test-User": str(self.user_id)})

    @task(10)
    def roulette_state(self):
        self.client.get("/miniapp/game/roulette/state", name="[B] Roulette state")

    @task(10)
    def game_state(self):
        self.client.get("/miniapp/game/state", name="[B] Game portfolio")

    @task(8)
    def buy(self):
        usdt = random.randint(10, 100)
        self.client.post("/miniapp/game/buy", json={"usdt": usdt},
                         name="[B] Buy position",
                         headers={"X-Test-User": str(self.user_id)})

    @task(3)
    def leaderboard(self):
        self.client.get("/miniapp/game/leaderboard", name="[B] Leaderboard")

    @task(2)
    def achievements(self):
        self.client.get("/miniapp/game/achievements", name="[B] Achievements")


class AIBotUser(HttpUser):
    """Волна B: отправляют ИИ-запросы (тяжелые)."""
    wait_time = between(2.0, 5.0)

    def on_start(self):
        self.user_id = random.randint(1000000, 9999999)

    @task(40)
    def ask_question(self):
        q = random.choice(QUESTION_POOL)
        resp = self.client.post("/miniapp/ask", json={"question": q},
                                name="[C] AI ask (submit)",
                                headers={"X-Test-User": str(self.user_id)})
        if resp.status_code == 200:
            data = resp.json()
            task_id = data.get("task_id", "")
            if task_id:
                time.sleep(0.5)
                for _ in range(10):
                    poll = self.client.get(f"/miniapp/ask/{task_id}",
                                           name="[C] AI ask (poll)",
                                           headers={"X-Test-User": str(self.user_id)})
                    if poll.status_code != 200:
                        break
                    status = poll.json().get("status", "")
                    if status in ("done", "error"):
                        break
                    time.sleep(0.3)

    @task(10)
    def timothy_analysis(self):
        self.client.get("/miniapp/news/timothy", name="[C] Timothy analysis")

    @task(5)
    def summary(self):
        self.client.get("/miniapp/summary", name="[C] AI Summary")

    @task(5)
    def agents(self):
        self.client.get("/agents", name="[C] List agents")

    @task(3)
    def agent_chat(self):
        name = random.choice(["marketbrain", "timothy"])
        q = random.choice(QUESTION_POOL)
        self.client.get(f"/agents/{name}?q={q}", name="[C] Agent chat")


class MixedWave(HttpUser):
    """Волна A+B+C в одном пользователе — максимальный хаос."""
    wait_time = between(0.1, 3.0)

    def on_start(self):
        self.user_id = random.randint(1000000, 9999999)

    @task(3)
    def mixed_get(self):
        endpoints = [
            "/miniapp/dashboard",
            "/miniapp/chart?timeframe=4h&limit=50",
            "/btc/indicators",
            "/miniapp/fear-greed",
            "/miniapp/news",
            "/miniapp/volatility",
            "/miniapp/predict",
            "/miniapp/game/state",
            "/miniapp/game/mining/state",
            "/miniapp/game/roulette/state",
            "/miniapp/game/leaderboard",
            "/miniapp/subscription/status",
        ]
        self.client.get(random.choice(endpoints), name="[Mix] GET")

    @task(2)
    def mixed_post(self):
        action = random.random()
        if action < 0.4:
            self.client.post("/miniapp/game/mining/click", json={},
                             name="[Mix] Mining click")
        elif action < 0.7:
            self.client.post("/miniapp/game/roulette",
                             json={"bet": random.randint(1, 3)},
                             name="[Mix] Roulette")
        elif action < 0.9:
            self.client.post("/miniapp/ask",
                             json={"question": random.choice(QUESTION_POOL)},
                             name="[Mix] AI ask")
        else:
            self.client.post("/miniapp/game/buy",
                             json={"usdt": random.randint(10, 50)},
                             name="[Mix] Buy")
