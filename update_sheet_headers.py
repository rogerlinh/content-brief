import sys
import os

# Đảm bảo import được code module dự án
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from modules.gsheet_logger import GSheetLogger

def main():
    print("Đang kết nối tới Google Sheet để cập nhật headers...")
    glog = GSheetLogger()
    if glog.connect():
        print("Đã apply headers mới (Cột Q, R) vào Google Sheet thành công!")
    else:
        print("Lỗi: Không thể kết nối tới Google Sheet.")

if __name__ == "__main__":
    main()
