from flask import Flask, render_template, redirect, url_for, request, session, jsonify, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import sqlite3
import json
import os

# 直接从代码中读取配置，不依赖环境变量
app = Flask(__name__, template_folder='templates')
app.secret_key = "your_predefined_secret_key_here"  # 与vercel.json保持一致

# 静态文件路由
@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('templates', path)

# 获取数据库路径（适配Vercel）
def get_db_path():
    return '/tmp/quiz.db' if 'VERCEL' in os.environ else 'quiz.db'

# 其余保持原有代码不变...
# 其余保持原有代码不变...

# 初始化Flask-Limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"]
)


# 初始化数据库
def init_db():
    conn = sqlite3.connect(get_db_path())
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS questions
                 (id INTEGER PRIMARY KEY, content TEXT, options TEXT, answer TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS teams
                 (id INTEGER PRIMARY KEY, name TEXT, points INTEGER, logo_url TEXT)''')
    conn.commit()
    conn.close()

# 获取随机题目
def get_random_questions():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM questions ORDER BY RANDOM() LIMIT 5')
    questions = [dict(row) for row in c.fetchall()]
    conn.close()
    return questions




@app.route('/yunwan')
def yunwan():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM teams ORDER BY points DESC')
    teams = [dict(row) for row in c.fetchall()]
    conn.close()
    return render_template('yunwan.html', teams=teams)

@app.route('/ranking')
def ranking():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute('SELECT id, name, points, logo_url FROM teams ORDER BY points DESC')
    teams = []

    for row in c.fetchall():
        team = dict(row)
        if team['logo_url'] and not team['logo_url'].startswith(('http://', 'https://')):
            team['logo_url'] = f"http://{team['logo_url']}"
        teams.append(team)

    max_points = max(team['points'] for team in teams) if teams else 0
    conn.close()

    for i, team in enumerate(teams[:3], 1):
        print(f"队伍 {i} logo_url: {team.get('logo_url')}")

    return render_template('ranking.html', teams=teams, max_points=max_points)

@app.route('/start_quiz', methods=['POST'])
@limiter.limit("5 per day")
def start_quiz():
    questions = get_random_questions()
    if not questions:
        return redirect(url_for('result', message="题库为空"))

    session['questions'] = questions
    session['current_index'] = 0
    return redirect(url_for('show_question'))

@app.route('/start/<team_name>')
def start_quiz_with_team(team_name):
    session['team_name'] = team_name
    questions = get_random_questions()
    if not questions:
        return redirect(url_for('result', message="题库为空"))

    session['questions'] = questions
    session['current_index'] = 0
    return redirect(url_for('show_question'))

@app.route('/questions')
def show_question():
    if 'questions' not in session or 'current_index' not in session:
        return redirect(url_for('home'))

    questions = session['questions']
    current_index = session['current_index']

    if current_index >= len(questions):
        return redirect(url_for('result', message="答题完成"))

    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM questions WHERE id = ?', (questions[current_index]['id'],))
    question = dict(c.fetchone())
    conn.close()

    if not question:
        return redirect(url_for('result', message="题目数据异常"))

    question['options'] = json.loads(question['options'])

    return render_template('questions.html',
                         question=question,
                         current_index=current_index + 1,
                         total=len(questions),
                         team_name=session.get('team_name', '未知队伍'))

@app.route('/submit_answer', methods=['POST'])
def submit_answer():
    try:
        if 'questions' not in session or 'current_index' not in session:
            return jsonify({
                'error': '会话已过期，请重新开始答题',
                'redirect': url_for('home')
            }), 400

        user_answer = request.form.get('answer')
        if user_answer not in ['A', 'B', 'C', 'D']:
            return jsonify({
                'error': '请选择有效选项（A/B/C/D）',
                'redirect': url_for('show_question')
            }), 400

        current_index = session['current_index']
        questions = session['questions']
        if current_index >= len(questions):
            return jsonify({
                'error': '题目索引越界',
                'redirect': url_for('result')
            }), 400

        conn = sqlite3.connect(get_db_path())
        c = conn.cursor()
        c.execute('SELECT answer FROM questions WHERE id = ?',
                 (questions[current_index]['id'],))
        correct_answer = int(c.fetchone()[0])
        conn.close()

        is_correct = (ord(user_answer) - ord('A') == correct_answer)

        if is_correct:
            conn = sqlite3.connect(get_db_path())
            c = conn.cursor()
            c.execute('UPDATE teams SET points = points + 1 WHERE name = ?',
                     (session.get('team_name'),))
            conn.commit()
            conn.close()

        session['current_index'] += 1
        session.modified = True

        return jsonify({
            'is_correct': is_correct,
            'correct_answer': chr(correct_answer + ord('A')),
            'redirect': url_for('show_question') if session['current_index'] < len(questions)
                        else url_for('result')
        })

    except Exception as e:
        error_msg = f'系统错误: {str(e)}'
        app.logger.error(f"SubmitAnswer Error: {error_msg}")
        return jsonify({
            'error': error_msg,
            'redirect': url_for('home')
        }), 500

def get_team_points(team_name):
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT points FROM teams WHERE name = ?', (team_name,))
    result = c.fetchone()
    conn.close()
    return result['points'] if result else 0

@app.route('/result')
def result():
    session.pop('questions', None)
    session.pop('current_index', None)

    message = request.args.get('message', '答题结束')
    team_name = session.get('team_name', '未知队伍')
    points = get_team_points(team_name)

    return render_template('result.html',
                         message=message,
                         team_name=team_name,
                         points=points)

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', port=port)
