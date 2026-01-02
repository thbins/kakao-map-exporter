# Kakao Map Exporter (지역+검색어 → 엑셀)

개인적으로 필요해서 제작한 카카오 로컬(장소) 검색 API를 이용해 **지역명 + 검색어**로 장소를 수집하고,
결과를 **엑셀(.xlsx)** 로 저장하는 데스크톱 앱입니다.

## 1. 준비물: 카카오 REST API 키 발급

카카오 Developers에서 **로컬(장소 검색)** REST API를 사용할 수 있도록 앱을 만들고,
REST API 키를 발급받습니다.

- 환경변수 또는 `.env` 파일로 키를 넣어야 실행됩니다.
- 키 파일은 **절대 GitHub에 커밋하지 마세요.**

## 2. 로컬 실행

### 2.1. Python 가상환경 생성 및 의존성 설치

#### macOS / Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### Windows (PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2.2. .env 설정
레포 루트에 .env 파일을 만들고 아래처럼 넣습니다:
```
KAKAO_REST_API_KEY=카카오_REST_API_키
```

## 3. 사용 방법

1. 검색어 입력 (예: 카페)
2. 지역명 입력 (예: 서울시청, 강남역, 부산 해운대)
3. (선택) 프랜차이즈 제외 체크
4. 검색 클릭(또는 Enter)
5. 결과 확인 후 엑셀로 저장… 클릭

## 4. Windows 실행 파일(.exe) 빌드

### 4.1. Windows에서 직접 빌드 (PyInstaller)

```bash
pip install -r requirements.txt
pyinstaller --noconsole --onefile desktop_app.py
```

결과물은 `dist\desktop_app.exe` 파일입니다.

### 4.2. GitHub Actions로 자동 빌드

```yaml
# .github/workflows/build-windows.yml
```

`v0.1.0` 같은 태그를 push하면 Actions가 Windows 러너에서 빌드하고,
Artifact로 `desktop_app.exe`를 업로드하도록 구성할 수 있습니다.