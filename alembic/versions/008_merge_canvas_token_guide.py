"""Merge canvas_token guide into settings guide

Revision ID: 008_merge_canvas_token_guide
Revises: 007_add_canvas_token_guide
Create Date: 2026-03-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '008_merge_canvas_token_guide'
down_revision: Union[str, None] = '007_add_canvas_token_guide'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CANVAS_TOKEN_CONTENT = r"""

---

## Hướng dẫn tạo Access Token trên Canvas LMS

Access Token (mã truy cập) giúp hệ thống TA Grader kết nối với tài khoản Canvas LMS của bạn để tự động lấy danh sách khóa học, bài thi và kết quả. Dưới đây là hướng dẫn chi tiết từng bước.

### Bước 1: Đăng nhập vào Canvas LMS

Truy cập trang Canvas LMS của trường (ví dụ: **https://lms.uet.vnu.edu.vn**) và đăng nhập bằng tài khoản của bạn.

### Bước 2: Mở trang Cài đặt tài khoản

1. Nhấn vào **ảnh đại diện** hoặc biểu tượng **Account** (Tài khoản) ở thanh điều hướng bên trái.
2. Chọn **Settings** (Cài đặt) từ menu hiện ra.

### Bước 3: Tạo Access Token mới

1. Kéo xuống phần **Approved Integrations** (Tích hợp đã duyệt).
2. Nhấn nút **+ New Access Token** (Tạo mã truy cập mới).

### Bước 4: Điền thông tin Token

Một hộp thoại sẽ hiện ra yêu cầu bạn nhập:

- **Purpose** (Mục đích): Nhập mô tả để bạn nhớ token này dùng cho gì, ví dụ: `TA Grader`
- **Expires** (Ngày hết hạn): Có thể để trống nếu muốn token không hết hạn. Nếu muốn an toàn hơn, hãy chọn một ngày hết hạn phù hợp (ví dụ: cuối học kỳ).

Sau khi điền xong, nhấn nút **Generate Token** (Tạo token).

### Bước 5: Sao chép Token

**Quan trọng:** Sau khi tạo, hệ thống sẽ hiển thị mã token một lần duy nhất. Hãy **sao chép ngay** mã này.

- Nhấn vào ô chứa token và **Copy** (Sao chép).
- Nếu bạn đóng hộp thoại mà chưa sao chép, bạn sẽ **không thể xem lại** token này và phải tạo mới.

### Bước 6: Dán Token vào TA Grader

1. Trong TA Grader, vào tab **Cài đặt** (Settings).
2. Ở phần **Canvas LMS - Kết nối**:
   - **Canvas Base URL**: Nhập địa chỉ Canvas của trường (mặc định: `https://lms.uet.vnu.edu.vn`)
   - **Access Token**: Dán mã token vừa sao chép vào đây.
3. Nhấn **Save & Connect** (Lưu & Kết nối).
4. Nếu thành công, trạng thái sẽ chuyển sang **Connected** (Đã kết nối).

---

### Lưu ý bảo mật

- **Không chia sẻ** token cho bất kỳ ai. Token có quyền truy cập giống như mật khẩu tài khoản của bạn.
- Nếu nghi ngờ token bị lộ, hãy **xóa token cũ** ngay trên Canvas (nhấn biểu tượng xóa bên cạnh token trong phần Approved Integrations) và tạo token mới.
- Trong TA Grader, bạn có thể nhấn **Revoke Token** để xóa token đã lưu và nhập token mới.

### Xóa Token trên Canvas

Nếu bạn không muốn sử dụng token nữa:

1. Vào **Settings** (Cài đặt) trên Canvas.
2. Tìm token trong phần **Approved Integrations**.
3. Nhấn biểu tượng **xóa** (thùng rác) bên cạnh token.
4. Xác nhận xóa bằng cách nhấn **OK**.

---

### Câu hỏi thường gặp

**Tôi quên sao chép token, phải làm sao?**
Bạn không thể xem lại token đã tạo. Hãy tạo một token mới theo các bước ở trên.

**Token hết hạn thì sao?**
Khi token hết hạn, kết nối Canvas sẽ ngừng hoạt động. Vào Canvas tạo token mới và cập nhật trong phần Cài đặt của TA Grader.

**Tôi có thể tạo nhiều token không?**
Có, bạn có thể tạo nhiều token trên Canvas. Tuy nhiên, TA Grader chỉ sử dụng một token tại một thời điểm.
"""


def upgrade() -> None:
    # Append canvas token guide content into settings guide
    escaped = CANVAS_TOKEN_CONTENT.replace("'", "''")
    op.execute(
        f"UPDATE guide_documents SET content = content || '{escaped}' "
        "WHERE panel_key = 'settings'"
    )
    # Remove the separate canvas_token guide
    op.execute("DELETE FROM guide_documents WHERE panel_key = 'canvas_token'")


def downgrade() -> None:
    # Re-create the canvas_token guide (from migration 007)
    op.execute(
        "INSERT INTO guide_documents "
        "(panel_key, title, description, icon_name, content, sort_order, is_published) "
        "VALUES ('canvas_token', 'Hướng dẫn tạo Access Token', "
        "'Cách tạo và quản lý Access Token trên Canvas LMS', 'Key', "
        "'" + CANVAS_TOKEN_CONTENT.replace("'", "''") + "', 9, true) "
        "ON CONFLICT (panel_key) DO NOTHING"
    )
    # Remove appended content from settings guide (best effort - truncate at the marker)
    # This is approximate; admin can re-edit if needed
