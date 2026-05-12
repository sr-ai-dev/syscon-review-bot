BUILTIN_RULES: dict[str, str] = {
    "architecture": (
        "아키텍처: 도메인 구조가 올바른지, 의존성 방향이 단방향인지, "
        "레이어 분리가 적절한지 검토하라. 모듈 간 결합도, 책임의 명확성도 본다.\n"
        "  - critical: 레이어 역참조 등 의존성 방향 위반으로 도메인 무결성 훼손\n"
        "  - warning: 모듈 간 결합도 과다, 책임 경계 불명확\n"
        "  - minor: 명명·구조 미세 개선"
    ),
    "type_safety": (
        "타입 안전성: 각 언어의 타입 시스템을 적극 활용하고 우회를 피했는지 검토하라. "
        "any/void*/raw type/dynamic dispatch 남발, 캐스팅 남용, nullable 처리 누락 등.\n"
        "  - critical: 런타임 크래시·NPE가 명백한 타입 우회\n"
        "  - warning: any/raw cast 남발, nullable 처리 누락\n"
        "  - minor: 타입 명시·세분화 권장"
    ),
    "code_quality": (
        "코드 품질: 중복 코드, 단일 책임 원칙 위반, 매직 넘버, "
        "과도하게 긴 함수가 있는지 검토하라.\n"
        "  - warning: SRP 위반, 매직 넘버 남발, 과도하게 긴 함수\n"
        "  - minor: 소량 중복, 명명 개선"
    ),
    "test_coverage": (
        "테스트 충분성: 비즈니스 로직 변경 시 테스트가 동반되었는지, "
        "버그 수정 시 재현 테스트가 포함되었는지 검토하라. "
        "UI/스타일링 변경은 테스트 불필요로 판단하라.\n"
        "  - warning: 비즈니스 로직 변경에 테스트 부재, 버그 픽스에 재현 테스트 없음\n"
        "  - minor: 엣지 케이스 보강 권장"
    ),
    "performance": (
        "성능: 불필요한 연산, 메모리 누수 가능성, O(n²) 루프, "
        "비효율적 자료구조/순회 패턴이 있는지 검토하라.\n"
        "  - critical: hot path의 O(n²)+ 복잡도, 명백한 메모리 누수\n"
        "  - warning: 비효율 자료구조, 불필요한 연산 반복\n"
        "  - minor: 미세 최적화 여지"
    ),
    "security": (
        "보안: SQL/명령어 인젝션, XSS, 인증/인가 누락, 민감정보 노출, "
        "경로 조작, 안전하지 않은 직렬화 등 보안 취약점이 있는지 검토하라.\n"
        "  - critical: SQL/명령어 인젝션, 인증·인가 우회, 민감정보 노출, RCE, 경로 조작\n"
        "  - warning: 보안 헤더 누락, 약한 입력 검증, 로깅에 토큰/PII 포함\n"
        "  - minor: 보안 권장사항 미준수 (방어 깊이 보강 수준)"
    ),
    "error_handling": (
        "에러 핸들링: 예외/오류를 무시(빈 catch, broad except, error 반환 무시)하거나, "
        "사용자에게 피드백 없는 silent failure가 있는지 검토하라.\n"
        "  - critical: silent failure로 데이터 손실·정합성 훼손, 트랜잭션 미롤백\n"
        "  - warning: 빈 catch, broad except, error 반환 무시\n"
        "  - minor: 에러 메시지 보강"
    ),
    "refactoring": (
        "리팩토링 기회: 긴 함수, 불명확한 이름, 반복 로직, "
        "추출 가능한 공통 패턴이 있는지 검토하라.\n"
        "  - warning: 긴 함수·반복 로직이 실수를 유발할 정도\n"
        "  - minor: 이름 개선, 추출 가능한 패턴 (권고 수준)"
    ),
    "documentation": (
        "문서 정합성: 비즈니스 로직 변경 시 관련 문서가 갱신되었는지, "
        "문서 내용과 실제 구현이 일치하는지 검토하라.\n"
        "  - warning: 비즈니스 로직 변경인데 관련 문서 미갱신, 문서와 구현 불일치\n"
        "  - minor: 표기·오타·문장 다듬기"
    ),
}
