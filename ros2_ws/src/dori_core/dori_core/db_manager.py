import sqlite3
import threading
from contextlib import closing
import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String

class TTSDatabaseManager:
    def __init__(self, db_path='tts_usage.db'):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        """데이터베이스 및 테이블 초기화 (WAL 모드 활성화)"""
        with self.lock:
            with closing(sqlite3.connect(self.db_path, check_same_thread=False)) as conn:
                # WAL 모드 활성화 (동시 읽기/쓰기 성능 대폭 향상)
                conn.execute('PRAGMA journal_mode=WAL;')
                with conn: # 트랜잭션 매니저 (자동 commit/rollback)
                    conn.execute('''
                        CREATE TABLE IF NOT EXISTS usage_log (
                            date TEXT PRIMARY KEY,
                            neural2 INTEGER DEFAULT 0,
                            wavenet INTEGER DEFAULT 0,
                            standard INTEGER DEFAULT 0
                        )
                    ''')

    def add_usage(self, date_str, model_name, char_count):
        """안전하게 글자 수를 누적하는 쓰기 메서드"""
        with self.lock:
            with closing(sqlite3.connect(self.db_path, check_same_thread=False)) as conn:
                with conn:
                    # 해당 날짜의 레코드가 없으면 0으로 생성
                    conn.execute('''
                        INSERT INTO usage_log (date) 
                        VALUES (?) 
                        ON CONFLICT(date) DO NOTHING
                    ''', (date_str,))
                    
                    # 선택된 모델의 글자 수 누적
                    conn.execute(f'''
                        UPDATE usage_log 
                        SET {model_name} = {model_name} + ? 
                        WHERE date = ?
                    ''', (char_count, date_str))

    def get_usage(self, date_str):
        """특정 날짜의 사용량을 가져오는 읽기 메서드"""
        with closing(sqlite3.connect(self.db_path, check_same_thread=False)) as conn:
            conn.row_factory = sqlite3.Row # 결과를 딕셔너리처럼 접근하기 위해 추가
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM usage_log WHERE date = ?', (date_str,))
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            return {'date': date_str, 'neural2': 0, 'wavenet': 0, 'standard': 0}
