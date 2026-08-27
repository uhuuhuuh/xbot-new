# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import random
import os
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from twitter.account import Account

# ログ設定
logging.basicConfig(level=logging.INFO, encoding='utf-8')
logger = logging.getLogger(__name__)

# テンプレートフォルダの絶対パス
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')

app = Flask(__name__, template_folder=TEMPLATE_DIR)
app.config['JSON_AS_ASCII'] = False
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tokens.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# レスポンスヘッダーにcharsetを強制
@app.after_request
def after_request(response):
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response

db = SQLAlchemy(app)

# ============================================================
# データベースモデル
# ============================================================
class TwitterToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    auth_token = db.Column(db.String(200), nullable=False)
    ct0 = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_tweet_at = db.Column(db.DateTime)
    tweet_count = db.Column(db.Integer, default=0)
    scheduled_hour = db.Column(db.Integer, default=0)
    scheduled_minute = db.Column(db.Integer, default=0)

class TweetLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token_id = db.Column(db.Integer, db.ForeignKey('twitter_token.id'))
    token_name = db.Column(db.String(100))
    tweet_text = db.Column(db.Text)
    tweet_id = db.Column(db.String(50))
    status = db.Column(db.String(20), default='success')
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ============================================================
# ツイートテンプレート
# ============================================================
TWEET_TEMPLATES = [
    "今日も一日頑張ろう！ #日記",
    "おはようございます！良い一日を☀️",
    "今日の天気は最高です！",
    "コーヒーを飲みながら考え事中☕",
    "新しいことに挑戦する時が来た！",
    "今日も素敵な日になりますように✨",
    "休憩時間に読書中📚",
    "美味しいランチを食べました！🍣",
    "今日の目標を達成しました！🎉",
    "夜はゆっくり過ごします🌙",
    "素晴らしいアイデアが浮かびました！💡",
    "頑張っている自分を褒めたい日",
    "今日の日没が美しかった🌅",
    "音楽を聴きながらリラックス🎵",
    "新しい友人と出会いました！",
    "今日も感謝の気持ちでいっぱいです🙏",
    "運動してリフレッシュ！🏃",
    "美味しいスイーツを見つけました🍰",
    "今日の小さな幸せに気づく",
    "明日も良い日になりますように🌟",
    "週末の予定を考え中🗓️",
    "今日の仕事は順調です💪",
    "新しいスキルを習得中📖",
    "美味しいコーヒーを発見！☕",
    "今日も笑顔でいよう😊",
    "素敵な音楽を見つけました🎶",
    "今日の夕日が綺麗だった🌇",
    "自分へのご褒美を考え中🎁",
    "新しい本を読み始めました📖",
    "今日も感謝の気持ちを忘れずに🙏",
    "いい天気だね！外に出かけよう🌤️",
    "今日のランチはカレーにしよう🍛",
    "集中力が続くように深呼吸🧘",
    "新しいプロジェクトが始まる！🚀",
    "今日は早く寝よう🌙",
    "友達と話すと元気が出る😊",
    "美味しいスイーツが食べたい🍰",
    "今日の夕飯何にしようかな🍳",
    "考えすぎずに行動しよう💪",
    "小さな幸せを大切に✨"
]

# ============================================================
# Twitterボット（非公式API）
# ============================================================
class TwitterBot:
    def __init__(self, auth_token, ct0=None):
        self.auth_token = auth_token
        self.ct0 = ct0
        self.account = None

    def authenticate(self):
        try:
            cookies = {"auth_token": self.auth_token}
            if self.ct0:
                cookies["ct0"] = self.ct0
            self.account = Account(cookies=cookies)
            self.account.me()
            if hasattr(self.account, 'cookies') and 'ct0' in self.account.cookies:
                self.ct0 = self.account.cookies['ct0']
            logger.info(f"認証成功: auth_token={self.auth_token[:10]}...")
            return True, self.ct0
        except Exception as e:
            logger.error(f"認証エラー: {e}")
            return False, None

    def post_tweet(self, text=None):
        try:
            if not self.account:
                success, _ = self.authenticate()
                if not success:
                    return False, "認証に失敗しました"
            if text is None:
                text = random.choice(TWEET_TEMPLATES)
            result = self.account.tweet(text)
            tweet_id = result.get('data', {}).get('create_tweet', {}).get('tweet_results', {}).get('result', {}).get('rest_id')
            logger.info(f"ツイート成功: {text}")
            return True, {'text': text, 'id': tweet_id}
        except Exception as e:
            logger.error(f"ツイート失敗: {e}")
            return False, str(e)

# ============================================================
# スケジューラー
# ============================================================
scheduler = BackgroundScheduler()

def scheduled_tweet(token_id):
    with app.app_context():
        try:
            token = TwitterToken.query.get(token_id)
            if not token or not token.is_active:
                return
            bot = TwitterBot(token.auth_token, token.ct0)
            success, result = bot.post_tweet()
            log = TweetLog(
                token_id=token.id,
                token_name=token.name,
                tweet_text=result['text'] if success else str(result),
                status='success' if success else 'error',
                error_message=None if success else str(result)
            )
            db.session.add(log)
            if success:
                token.last_tweet_at = datetime.utcnow()
                token.tweet_count += 1
                if bot.ct0:
                    token.ct0 = bot.ct0
                token.scheduled_hour = random.randint(0, 23)
                token.scheduled_minute = random.randint(0, 59)
                db.session.commit()
                update_token_schedule(token.id)
                logger.info(f"{token.name}: 次回 {token.scheduled_hour:02d}:{token.scheduled_minute:02d}")
            else:
                db.session.commit()
                logger.error(f"{token.name}: ツイート失敗 - {result}")
        except Exception as e:
            logger.error(f"scheduled_tweet 例外: {e}")
            db.session.rollback()

def update_token_schedule(token_id):
    with app.app_context():
        token = TwitterToken.query.get(token_id)
        if not token or not token.is_active:
            return
        job_id = f"tweet_{token_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        scheduler.add_job(
            func=scheduled_tweet,
            trigger=CronTrigger(hour=token.scheduled_hour, minute=token.scheduled_minute),
            args=[token_id],
            id=job_id,
            replace_existing=True
        )
        logger.info(f"スケジュール設定: {token.name} → {token.scheduled_hour:02d}:{token.scheduled_minute:02d}")

def init_scheduler():
    with app.app_context():
        tokens = TwitterToken.query.filter_by(is_active=True).all()
        for token in tokens:
            if token.scheduled_hour == 0 and token.scheduled_minute == 0:
                token.scheduled_hour = random.randint(0, 23)
                token.scheduled_minute = random.randint(0, 59)
                db.session.commit()
            update_token_schedule(token.id)
        scheduler.start()
        logger.info(f"スケジューラー起動 (アクティブトークン: {len(tokens)})")

# ============================================================
# Flask ルート
# ============================================================
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        auth_token = request.form.get('auth_token', '').strip()
        name = request.form.get('name', '').strip() or f"アカウント_{datetime.now().strftime('%H%M%S')}"
        if not auth_token:
            flash('auth_token を入力してください', 'error')
            return redirect(url_for('index'))
        bot = TwitterBot(auth_token)
        success, ct0 = bot.authenticate()
        if not success:
            flash('認証に失敗しました。auth_token が正しいか確認してください', 'error')
            return redirect(url_for('index'))
        token = TwitterToken(
            name=name,
            auth_token=auth_token,
            ct0=ct0,
            scheduled_hour=random.randint(0, 23),
            scheduled_minute=random.randint(0, 59)
        )
        db.session.add(token)
        db.session.commit()
        update_token_schedule(token.id)
        flash(f'✅ トークン "{name}" を追加しました。{token.scheduled_hour:02d}:{token.scheduled_minute:02d} にツイート予定', 'success')
        return redirect(url_for('index'))
    tokens = TwitterToken.query.all()
    return render_template('index.html', tokens=tokens)

@app.route('/toggle/<int:token_id>')
def toggle_token(token_id):
    token = TwitterToken.query.get_or_404(token_id)
    token.is_active = not token.is_active
    db.session.commit()
    if token.is_active:
        update_token_schedule(token.id)
        flash(f'✅ "{token.name}" を有効化しました', 'success')
    else:
        job_id = f"tweet_{token_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        flash(f'⏸️ "{token.name}" を無効化しました', 'success')
    return redirect(url_for('index'))

@app.route('/delete/<int:token_id>')
def delete_token(token_id):
    token = TwitterToken.query.get_or_404(token_id)
    job_id = f"tweet_{token_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    db.session.delete(token)
    db.session.commit()
    flash('トークンを削除しました', 'success')
    return redirect(url_for('index'))

@app.route('/test/<int:token_id>')
def test_tweet(token_id):
    token = TwitterToken.query.get_or_404(token_id)
    bot = TwitterBot(token.auth_token, token.ct0)
    success, result = bot.post_tweet()
    log = TweetLog(
        token_id=token.id,
        token_name=token.name,
        tweet_text=result['text'] if success else str(result),
        status='success' if success else 'error',
        error_message=None if success else str(result)
    )
    db.session.add(log)
    db.session.commit()
    if success:
        flash(f'✅ テストツイート成功: {result["text"]}', 'success')
    else:
        flash(f'❌ テストツイート失敗: {result}', 'error')
    return redirect(url_for('index'))

@app.route('/reschedule/<int:token_id>')
def reschedule(token_id):
    token = TwitterToken.query.get_or_404(token_id)
    token.scheduled_hour = random.randint(0, 23)
    token.scheduled_minute = random.randint(0, 59)
    db.session.commit()
    if token.is_active:
        update_token_schedule(token.id)
    flash(f'🔄 スケジュールを再設定: {token.scheduled_hour:02d}:{token.scheduled_minute:02d}', 'success')
    return redirect(url_for('index'))

@app.route('/logs')
def logs():
    logs = TweetLog.query.order_by(TweetLog.created_at.desc()).limit(100).all()
    return render_template('logs.html', logs=logs)

@app.route('/logs/<int:token_id>')
def token_logs(token_id):
    token = TwitterToken.query.get_or_404(token_id)
    logs = TweetLog.query.filter_by(token_id=token_id).order_by(TweetLog.created_at.desc()).limit(50).all()
    return render_template('token_logs.html', token=token, logs=logs)

# ============================================================
# 起動
# ============================================================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        init_scheduler()
    print("\n" + "=" * 50)
    print("🐦 X自動ツイートアプリ（非公式API版）")
    print("🌐 http://localhost:5000 にアクセス")
    print("📝 auth_token を入力するだけで自動ツイート開始！")
    print("⚠️ 自己責任でご利用ください")
    print("=" * 50 + "\n")
    try:
        app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
    except KeyboardInterrupt:
        scheduler.shutdown()
        print("\nアプリを終了しました")