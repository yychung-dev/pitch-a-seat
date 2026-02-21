"""
test_auth_utils.py
Unit Tests for utils/auth_utils.py

Test Coverage: 22 test functions using pytest framework with AAA pattern (Arrange-Act-Assert)
Includes positive tests, negative tests, and boundary tests.

Test Classes:
- TestHashPassword (4 tests)
  Password hashing: returns string, not equal to original, different each time, bcrypt format

- TestVerifyPassword (4 tests)
  Password verification: correct passes, wrong fails, empty fails, case sensitive

- TestCreateAccessToken (4 tests)
  Token creation: returns string, valid JWT format, contains user data, custom expiry

- TestVerifyToken (6 tests)
  Token verification: valid, invalid, empty, tampered, expired, missing user_id

- TestGetCurrentUser (4 tests)
  Header validation: correct format, missing, invalid format, empty Bearer

Dependencies: conftest.py provides sample_password and sample_user_data fixtures
"""


# 流程: 在測試函數中, 用 假的測試資料 呼叫執行 真實商業邏輯函數, 測試輸出結果是否如設計開發時的預期
# AAA 模式: (1) Arrange(準備): 準備測試需要的資料 (2) Act(執行): 呼叫要被測試的函數 (商業邏輯函數) (3) Assert(驗證): 檢查結果是否符合預期
# 依賴: conftest.py 提供的 sample_password 和 sample_user_data fixture


import pytest
from datetime import timedelta
from fastapi import HTTPException


# 從 utils.auth_utils import 要測試的 5 個函數
from utils.auth_utils import (
    hash_password,
    verify_password,
    create_access_token,
    verify_token,
    get_current_user
)


# ==============================================
# 測試 hash_password 函數
class TestHashPassword:
    # hash_password 函數: 負責把使用者的明碼密碼加密 (用途: 會員註冊時，將使用者明碼密碼雜湊加密成亂碼後存入資料庫)。
    # 測試 hash_password 函數的原因: (1) 確保密碼有被正確加密後存入資料庫，而非把明碼密碼存入資料庫 (2) 確保每次加密的結果都不一樣（有加 salt）
    
    # 測試 1: hash_password 應該回傳字串 (最基本的測試，確保函數有正確回傳值)
    def test_hash_password_returns_string(self, sample_password):
        # Arrange（準備）- 使用 fixture 提供的密碼
        password = sample_password
        
        # Act（執行）
        result = hash_password(password)
        
        # Assert（驗證）
        assert isinstance(result, str)  # 結果應該是字串
        assert len(result) > 0          # 結果不應該是空字串


    # 測試 2: 雜湊後的密碼不應該等於原始密碼 (確保密碼有被加密，而不是直接存明碼)
    def test_hash_password_not_equal_to_original(self, sample_password):
        hashed = hash_password(sample_password)
        
        # 雜湊結果不應該等於原始密碼
        assert hashed != sample_password


    # 測試 3: 同樣的密碼，每次雜湊結果都不一樣 (bcrypt 的特性: 每次會用不同的 salt, 所以同樣的密碼會產生不同的雜湊值。是安全的設計 )
    def test_hash_password_different_each_time(self, sample_password):

        hash1 = hash_password(sample_password)
        hash2 = hash_password(sample_password)
        
        # 兩次雜湊結果應該不同
        assert hash1 != hash2


    # 測試 4: bcrypt 雜湊應該以 $2b$ 開頭 (確保商業邏輯函數確實有使用了 bcrypt 演算法)
    def test_hash_password_starts_with_bcrypt_prefix(self, sample_password):
        hashed = hash_password(sample_password)
        
        # bcrypt 雜湊值的格式是 $2b$...
        assert hashed.startswith("$2b$")
# ==============================================




# ==============================================
# 測試 verify_password 函數
class TestVerifyPassword:
    # verify_password 函數: 負責在使用者登入時比對 「其在前端輸入的密碼」 & 「資料庫存的密碼」 是否相同
    
    # 測試 verify_password 函數的原因: (1)確保正確的密碼可以通過驗證 (2)確保錯誤的密碼會被拒絕 (3)這是登入功能的核心。若出錯：正確密碼被拒絕 -> 使用者無法登入; 錯誤密碼被接受 -> 任何人都能登入任何帳號


    # 測試 1: 正確的密碼應該驗證通過 (正向測試 (Happy Path))
    # bcrypt.checkpw 會自動從儲存在資料庫的雜湊亂碼中解析並取出「最初用來產生雜湊密碼的 salt值」
    def test_verify_password_correct(self, sample_password):
        # Arrange
        hashed = hash_password(sample_password)        
        # Act
        result = verify_password(sample_password, hashed)        
        # Assert
        assert result is True


    # 測試 2: 錯誤的密碼應該驗證失敗 (負向測試 (Error Case)): 確保不會因為 Bug 讓任何密碼都能驗證通過
    def test_verify_password_wrong(self, sample_password):
        hashed = hash_password(sample_password)
        wrong_password = "WrongPassword456"
        
        result = verify_password(wrong_password, hashed)
        
        assert result is False



    # 測試 3: 空密碼應該驗證失敗    
    def test_verify_password_empty_fails(self, sample_password):
        hashed = hash_password(sample_password)
        
        result = verify_password("", hashed)
        
        assert result is False



    # 測試 4: 密碼應該區分大小寫 ("Password" 和 "password" 是不同的密碼)
    def test_verify_password_case_sensitive(self):
        original = "MyPassword123"
        hashed = hash_password(original)
        
        # 大小寫不同，應該驗證失敗
        assert verify_password("mypassword123", hashed) is False
        assert verify_password("MYPASSWORD123", hashed) is False
        
        # 大小寫完全相同，應該驗證成功
        assert verify_password("MyPassword123", hashed) is True
# ==============================================




# ==============================================
# 測試 create_access_token 函數
class TestCreateAccessToken:   
    # create_access_token 函數: 負責在使用者登入後生成 JWT Token。    
    # 測試 create_access_token 函數的原因: (1)確保 token 格式 正確（可以被解碼）(2)確保 token 包含的使用者資訊 正確。否則, 若 Token 出錯, 使用者的身份資訊也會錯誤

    
    # 測試 1: create_access_token 應該回傳字串
    def test_create_token_returns_string(self, sample_user_data):
        token = create_access_token(data=sample_user_data)
        
        assert isinstance(token, str)   # 結果應該是字串
        assert len(token) > 0           # 結果不應該是空字串


    # 測試 2: token 應該是有效的 JWT 格式: JWT 格式: xxxxx.yyyyy.zzzzz (三段，用點分隔）
    def test_create_token_is_valid_jwt_format(self, sample_user_data):
        token = create_access_token(data=sample_user_data)
        
        # JWT 應該有三段
        parts = token.split(".")  # parts 類似: ['www', 'google', 'com'] 
        # .split(".") 是字串物件的一個方法，作用: 以點號（.）作為分隔符號將字串拆分成一個 List
        assert len(parts) == 3



    # (最重要的測試之一) 測試 3: token 解碼後應該包含正確的使用者資料 (確保 token 裡面的資料是對的)
    def test_create_token_contains_user_data(self, sample_user_data):
        token = create_access_token(data=sample_user_data)
        
        # 用 verify_token 解碼，檢查內容
        decoded = verify_token(token)
        
        assert decoded["user_id"] == sample_user_data["id"]
        assert decoded["email"] == sample_user_data["email"]
        assert decoded["name"] == sample_user_data["name"]


    # 測試 4: 可以自訂 token 過期時間, 測試 「傳入自訂 expires_delta 參數時，函數能正常執行」
    # 防範的錯誤：expires_delta 參數的處理邏輯若有 Bug，可能導致程式崩潰, 造成函數執行失敗。 例如：型別轉換錯誤、None 處理不當、計算錯誤等
    def test_create_token_with_custom_expiry(self, sample_user_data):

        # 設定 1 小時後過期
        token = create_access_token(
            data=sample_user_data,
            expires_delta=timedelta(hours=1)
        )
        
        # 只要能成功建立 JWT 字串即可算通過測試，詳細過期測試是寫在 TestVerifyToken 測試中
        assert isinstance(token, str)

    # -------------------
    # 這個測試有在呼叫 create_access_token 這個原始商業函數時傳入「expires_delta=timedelta(hours=1)」: 若處理邏輯有 Bug 導致崩潰，這個測試就不會通過。所以這個測試「只能確保不會崩潰」，「無法確保參數真的有被使用」。詳細說明: 
    # 1.若 原始商業函數裡的 expires_delta 相關的程式碼處理邏輯被寫壞 而導致函數崩潰, 這個測試會不通過 (開發者會發現原始商業函數有問題)
    #   - 因為 測試無法順利執行原始商業函數而得到字串回傳，那這個測試就不會通過
    # 2.若 原始商業函數裡的 expires_delta 相關的程式碼處理邏輯被寫壞 但不至於導致函數崩潰 (例: 傳入的 expires_delta 參數被忽略), 這個測試會通過 (開發者不會發現原始商業函數有問題)
    #   - 因為 這個測試「無法」直接發現參數被忽略。若傳入的 expires_delta 參數被忽略 (eg.有人不小心把原始商業邏輯函數的 if expires_delta 刪掉了，會變成「不管傳什麼 expires_delta，都會被忽略，永遠用預設值」): 函數還是會正常執行, 函數還是會回傳一個有效的 JWT 字串, 只是過期時間用了預設值，不是測試傳入的 1 小時, 所以 assert isinstance(token, str) 還是會通過

    # -------------------
    # 注意: 只確保函數能執行完畢並回傳字串, 這證明「傳入 expires_delta 時函數能走通, 不會崩潰, 但不代表有正確運用傳入的 expires_delta」, 無法證明「expires_delta 有被正確使用」
    # 注意: 這個測試「無法」檢測 expires_delta 是否真的被使用, 如果參數被忽略但函數沒崩潰，這個測試還是會通過。若要驗證「過期時間是否正確」，需要在 TestVerifyToken 中測試    

    # 若想「真正驗證 expires_delta 有被使用」（不是被忽略）的做法: eg. 建立一個 5 秒後過期的 token, 直接解碼 token，檢查過期時間, 計算過期時間與現在的差距, 應該大約是 5 秒（允許 1 秒誤差）

    # -------------------
    ### 完整的測試設計思路
    # 測試 create_access_token 的 expires_delta 參數：
    # 兩個測試搭配，才能完整驗證 expires_delta 功能。
    #  test_create_token_with_custom_expiry                   
    #   (1)目的：確保傳入參數時「不會崩潰」                        
    #   (2)方法：傳入參數，檢查回傳是字串                          
    #   (3)能發現的問題：參數處理邏輯導致崩潰                      
    #   (4)無法發現的問題：參數被忽略但沒崩潰                          
    # 
    #  test_verify_expired_token_raises_error                 
    #   (1) 目的：確保過期機制有作用                                   
    #   (2) 方法：建立已過期的 token，驗證會被拒絕                       
    #   (3) 能發現的問題：過期檢查沒作用、expires_delta 被忽略           
# ==============================================





# ==============================================
# (最重要的測試) 測試 verify_token 函數
class TestVerifyToken:    
    # verify_token 函數: 負責驗證從前端傳來的使用者的 token 是否有效    
    # 測試 verify_token 函數的原因: 這個函數決定「誰可以存取受保護的 API」, 如果這個函數有 Bug, 可能會 (1)讓非法使用者通過驗證（安全漏洞）(2)讓合法使用者被拒絕（功能壞掉）

    # 測試做法: 
    # (1) with pytest.raises(HTTPException) 檢查:原始函數「有沒有」正確拋出例外 (例外的「類型」是否正確: 必須是 HTTPException)
    # (2) assert exc_info.value.status_code == 401 檢查: 例外的「內容」對不對 (status_code 是否正確，eg. 必須是 401)」
    # (3) with ... as : 進入 with 區塊時：準備捕捉例外 (進入「捕捉例外」模式, 準備捕捉 HTTPException), 離開 with 區塊時：檢查是否有捕捉到預期的例外


    # 測試 1: 有效的 token 應該驗證成功 (最基本的「正向測試」)
    def test_verify_valid_token(self, sample_user_data):

        # Arrange - 先建立一個有效的 token
        token = create_access_token(data=sample_user_data)
        
        # Act - 驗證這個 token
        result = verify_token(token)
        
        # Assert - 應該回傳正確的使用者資料
        assert result["user_id"] == sample_user_data["id"]
        assert result["email"] == sample_user_data["email"]
        assert result["name"] == sample_user_data["name"]


    # 測試 2: 【無效的 token】無效的 token 應該拋出 401 錯誤 (確保亂碼 token 不會通過驗證 ) (
    # 用 設計好的例外情境資料 去跑 真實的商業邏輯函數 所得出的例外結果, 要確實與 測試函數設計好的例外結果(status code 必須是 401) 相符
    def test_verify_invalid_token_raises_error(self):

        invalid_token = "this.is.not.a.valid.jwt.token"
        
        # pytest.raises 用來測試「預期會拋出例外」的情況
        with pytest.raises(HTTPException) as exc_info:
            verify_token(invalid_token)  # 確保格式錯誤 (亂打字串)的 token 會進入 verify_token 函數中的 jwt.PyJWTError
        
        # 檢查錯誤的 status_code
        assert exc_info.value.status_code == 401


    # 測試 3: 【無效的 token】空 token 應該拋出錯誤
    def test_verify_empty_token_raises_error(self):
        with pytest.raises(HTTPException) as exc_info:
            verify_token("")    # 確保空字串的 token 會進入 verify_token 函數中的 jwt.PyJWTError (因為: 空字串不是有效的 JWT 格式, 所以: jwt.decode 拋出 jwt.PyJWTError（或其子類別）)
        
        assert exc_info.value.status_code == 401


    # (非常重要的安全測試) 測試 4: 【無效的 token】被竄改的 token 應該驗證失敗 : 確保有人修改 token 內容後會被發現
    def test_verify_tampered_token_raises_error(self, sample_user_data):

        # 先建立有效 token
        token = create_access_token(data=sample_user_data)
        
        # 然後竄改這個 token 的內容（ 修改 JWT 字串的最後5個字元, 這樣竄改後的字串還是正確的 token 三段格式結構，表示「內容被竄改，但格式看起來還像JWT，符合惡意竄改可能的做法」）
        tampered_token = token[:-5] + "XXXXX"
        
        with pytest.raises(HTTPException) as exc_info:
            verify_token(tampered_token)  # 確保錯誤(不一致)的簽名的 token 會進入 verify_token 函數中的 jwt.PyJWTError
        
        assert exc_info.value.status_code == 401


    # 測試 5: 【過期的 token】過期的 token 應該被拒絕: 測試 token 的過期機制是否正常運作 (若 token 本身的 exp 已過期, 要能被 jwt.decode方法 捕捉到並進入 jwt.ExpiredSignatureError, 印出 401 錯誤)
    def test_verify_expired_token_raises_error(self, sample_user_data):

        # 建立一個「已經過期」的 token（過期時間設為 -1 秒）
        expired_token = create_access_token(
            data=sample_user_data,
            expires_delta=timedelta(seconds=-1)  # 負數(減一秒) = 直接用jwt.encode()生成一個已經過期的 token (現在 datatime.utcnow 是 2025-02-01 10:30:00, expires_delta 就會是 2025-02-01 10:29:59)
        )
        
        with pytest.raises(HTTPException) as exc_info:
            verify_token(expired_token)   # jwt.decode 時會檢查 token 中的 exp (過期時間) (1705312199) 和 now (1705312200) , 若 exp < now, 就會拋出 jwt.ExpiredSignatureError
        
        assert exc_info.value.status_code == 401
        assert "過期" in exc_info.value.detail  # 錯誤訊息中應該要有關鍵字提到「過期」(依 verify_token 函數的設計, 若走進 jwt.ExpiredSignatureError, detail 必須是「Token 已過期，請重新登入」)


    # 測試 6: 【內容有問題的 token】缺少 user_id 的 token 應該被拒絕: 確保即使 token 格式正確，但內容不完整也會被拒絕 (必須進入 verify_token 設計好的 401錯誤 (detail: Token payload invalid))
    def test_verify_token_missing_user_id_raises_error(self):

        # 建立一個沒有 id 的 token 
        data_without_id = {"email": "test@example.com", "name": "Test"}
        token = create_access_token(data=data_without_id)
        
        with pytest.raises(HTTPException) as exc_info:
            verify_token(token)   
            # verify_token 函數的流程: jwt.decode成功 (因為格式正確、簽名正確、沒有過期), 但下一行 user_id: int = payload.get("id") 會得到 None, 因為payload裡沒有"id"這個key, 進到if user_id is None區塊, raise HTTPException(status_code=401, detail="Token payload invalid")
        
        assert exc_info.value.status_code == 401
# ==============================================




# ==============================================
# 測試 get_current_user 函數
class TestGetCurrentUser:    
    # get_current_user 函數是 FastAPI 的 Dependency, 負責從 HTTP Request Header 取得 token 並驗證    
    # 測試重點：(1) 是否正確檢查 Header 格式(Bearer xxx) (if not authorization.startswith("Bearer ")) (2) 缺少 Header 時是否正確拒絕 (if authorization is None)


    # 測試 1: 正確格式的 Authorization header 應該通過 (正向測試)
    def test_get_current_user_valid_header(self, sample_user_data):
        # 建立有效 token
        token = create_access_token(data=sample_user_data)
        
        # 模擬 HTTP Header 格式 (真實情境是「由前端 fetch 後端 API時手動加上 Bearer 前綴傳到後端」, 測試時手動加上以符合真實情境)
        auth_header = f"Bearer {token}"
        
        result = get_current_user(authorization=auth_header)
        
        assert result["user_id"] == sample_user_data["id"] # 正確格式的狀況下，經由 get_current_user 函數和 verify_token 函數decode 出來的user_id，要和原先用 create_access_token 函數 encode 前的 user_id 相同，這樣才是 get_current_user 函數通過測試的情境


    # 測試 2: 缺少 Authorization Header 時應該拋出 401, 且錯誤訊息是原始函數設計的「 Missing or invalid Authorization header 」 (if authorization is None 的情形)
    def test_get_current_user_missing_header(self):
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(authorization=None)
        
        assert exc_info.value.status_code == 401
        assert "Missing" in exc_info.value.detail # 檢查錯誤訊息是否包含關鍵字「Missing」(因為原始函數設計的錯誤訊息是「Missing or invalid Authorization header」 )


    # 測試 3: 錯誤的 header 格式應該被拒絕 (if not authorization.startswith("Bearer ")的情形)
    def test_get_current_user_invalid_format(self):
        # (1) 正確格式: Bearer xxxxx (2) 錯誤格式: 直接放 token (沒有 Bearer 前綴)
        
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(authorization="some-token-without-bearer")
        
        assert exc_info.value.status_code == 401


    # 測試 4: Bearer 後面沒有 token 應該被拒絕 (真實情境: Token 只有 Bearer 前綴但後面是空的的情形, 在get_current_user函數中, 能通過 if authorization is None or not authorization.startswith("Bearer "), 但走完 strip 後會只剩空字串才進到 verify_token 函數, 就會因 token 為空字串而被判定為「無效的字串」, 而被拒絕)
    def test_get_current_user_empty_bearer(self):
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(authorization="Bearer ")          
        assert exc_info.value.status_code == 401


    # --------------
    # authorization = "Bearer " -> authorization.startswith("Bearer ") -> True -> 不會進入if authorization is None or not authorization.startswith("Bearer ") -> 執行 「token = "Bearer ".replace("Bearer ", "").strip()」 -> token = "" (空字串) -> verify_token("") -> 失敗 -> 這就是測試：「只有 Bearer 前綴但沒後續 token」

    # --------------
    # 這個測試傳入的參數"Bearer "後面要空一格，否則執行 get_current_user 函數時會先進到 if not authorization.startswith("Bearer ") 這個區塊就不通過而raise錯誤 (因為檢查前綴時會檢查Bearer後面要空一格. 雖然在商業邏輯沒問題 (因為要操作之前會先用strip防禦性地處理空格問題). 但單元測試是反過來操作測試, 所以需要考量這個問題)

    # --------------
    # 測試 2 檢查 "Missing" 可以確認：錯誤確實是在 get_current_user 被擋住的，而不是「漏進去」到 verify_token 才被擋。   
    
    # --------------
    
    # 背景：get_current_user 函數內部會呼叫 verify_token 函數，兩個函數都可能拋出 401 錯誤

    # 1. 測試 2（test_get_current_user_missing_header）：關心「是哪個商業邏輯函數拒絕的」, 因為「沒帶 Header」和「token 無效」是不同的問題, 需要區分才能正確排查真實問題是什麼:
    # 情境一: authorization=None, 錯誤訊息: "Missing or invalid Authorization header", 被誰擋住: get_current_user（第一道防線）
    # 情境二: authorization="Bearer invalid", 錯誤訊息: "無效的 token", 被誰擋住: verify_token（第二道防線）

    # 檢查 "Missing" in detail 是為了確認錯誤發生在正確的位置：
    # (1)如果看到 "Missing"，代表錯誤在 get_current_user 被正確擋住
    # (2)如果看到 "無效的 token"，代表程式邏輯有問題，None 不該漏進去到 verify_token

    # 假設 get_current_user函數被改成「沒檢查 None, 只檢查 有無 Bearer前綴」(eg.「if not authorization.startswith("Bearer "):」). 若 authorization 真的是 None, 那走進「if not authorization.startswith("Bearer "):」這行時程式就會崩潰. 這種情況下, 若測試函數沒檢查 Missing 而只檢查 401, 測試還是會通過 (因為某處還是拋出了 401), 但實際商業邏輯 get_current_user函數 程式碼有 bug.



    # 2.測試 4（test_get_current_user_empty_bearer）：只關心「空 token 會不會被拒絕」、不關心「是哪個商業邏輯函數擋住的」, 只要「有被拒絕就對了」
    # 這個測試不關心是哪個函數擋住的，因為：
    # (1)從使用者角度："Bearer " 後面沒東西，應該被拒絕 → 只要有被拒絕就對了
    # (2)從實作角度：被 verify_token 擋住也是合理的，不算 Bug
    # (3)測試目的：確保「空 token」這個邊界情況不會意外通過

    
    # 3.總結: 
    # 測試     傳入值        測試目的                是否檢查錯誤訊息
    # 測試2    None         確認第一道防線有作用      檢查 "Missing"
    # 測試4    "Bearer "    確認空 token 會被拒絕    只檢查 401 即可
    
# ==============================================


