# pytest 共用設定檔 (conftest.py)
# 所有測試都能用 conftest 裡的東西: conftest.py 檔案會被 pytest 自動載入, 提供: 1. 共用的 fixture (測試用的預設資料或物件) 2. 設定 Python path, 讓測試可以 import 專案的模組

import pytest
import sys
import os

# 把專案根目錄 (例如："/home/user/pitchaseat") 加入 Python 的搜尋路徑 (sys.path 目錄)，並把專案根目錄放在sys.path清單的最前面
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))



# Fixtures（共用測試資料）

# 提供一組測試用的使用者資料
@pytest.fixture
def sample_user_data():
    return {
        "id": 123,
        "email": "test@example.com",
        "name": "測試使用者"
    }


# 提供測試用的密碼
@pytest.fixture
def sample_password():
    return "MySecurePassword123"






# ============================================

# ------------------------------
# Fixture 是 pytest 提供的功能，用來「準備測試需要的東西」，分兩種。例如：(1)測試用的假資料(例如: 預設的使用者 ID、Email)、(2)測試用的假物件 (例如: 模擬的資料庫連線或模擬的 API client)等。目前寫的測試只需要假資料，因為測試的函數是純函數，不需要連資料庫。
# 優點：不用在每個測試函數裡重複寫準備程式碼
# ------------------------------

# ------------------------------
# 測試函數使用 fixture 的方式，舉例：
#   def test_something(sample_user_data):
#       「sample_user_data」 這個傳入的參數, 就會是 fixture 內準備好的這組 dict 資料
# ------------------------------

# ------------------------------
# 裝飾器: 「包裝」一個函數，賦予它額外的功能
# 有裝飾器：pytest 會把它當作「fixture」處理

# @pytest.fixture 告訴 pytest：
# 1.「這個函數是一個 fixture，不是測試」 -> pytest 不會把它當作測試來執行 
# 2.「當測試函數需要這個名字的參數時，自動呼叫這個函數」-> 測試函數寫 def test_xxx(sample_user_data) -> pytest 自動呼叫 sample_user_data() 並把結果傳進去 
# 3.「每個測試都會得到一份新的資料」-> 測試之間不會互相影響
# ------------------------------

# ------------------------------
# 把專案根目錄 (例如："/home/user/pitchaseat") 加入 Python 的搜尋路徑 (sys.path 目錄)，並把專案根目錄放在sys.path清單的最前面:
# 這樣測試時才能 import 在專案根目錄之下的模組（如 utils.auth_utils）( 因為 pytest 是直接讀取 tests 資料夾，所以 sys.path 裡只有 /home/user/pitchaseat/tests，而沒有專案根目錄 /home/user/pitchaseat/，所以必須手動把專案根目錄加到sys.path清單中 )
# ------------------------------

# ============================================