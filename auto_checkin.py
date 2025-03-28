import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Callable, Dict, List, Optional

import requests
from loguru import logger
from pydantic import BaseModel, Field

from ext_bark import send_bark_notification


class Response(BaseModel):
    code: int = Field(..., alias="code", description="返回值")
    msg: str = Field(..., alias="msg", description="提示信息")
    success: Optional[bool] = Field(None, alias="success", description="token有时才有")
    data: Optional[Any] = Field(None, alias="data", description="请求成功才有")


class KurobbsClientException(Exception):
    """Custom exception for Kurobbs client errors."""
    pass


class KurobbsClient:
    FIND_ROLE_LIST_API_URL = "https://api.kurobbs.com/user/role/findRoleList"
    SIGN_URL = "https://api.kurobbs.com/encourage/signIn/v2"
    USER_SIGN_URL = "https://api.kurobbs.com/user/signIn"

    def __init__(self, token: str):
        self.token = token
        self.result: Dict[str, str] = {}
        self.exceptions: List[Exception] = []

    def get_headers(self) -> Dict[str, str]:
        """Get the headers required for API requests."""
        return {
            "osversion": "Android",
            "devcode": "2fba3859fe9bfe9099f2696b8648c2c6",
            "countrycode": "CN",
            "ip": "10.0.2.233",
            "model": "2211133C",
            "source": "android",
            "lang": "zh-Hans",
            "version": "1.0.9",
            "versioncode": "1090",
            "token": self.token,
            "content-type": "application/x-www-form-urlencoded; charset=utf-8",
            "accept-encoding": "gzip",
            "user-agent": "okhttp/3.10.0",
        }

    def make_request(self, url: str, data: Dict[str, Any]) -> Response:
        """Make a POST request to the specified URL with the given data."""
        headers = self.get_headers()
        response = requests.post(url, headers=headers, data=data)
        res = Response.model_validate_json(response.content)
        logger.debug(res.model_dump_json(indent=2, exclude={"data"}))
        return res

    def get_user_game_list(self, game_id: int) -> List[Dict[str, Any]]:
        """Get the list of games for the user."""
        data = {"gameId": game_id}
        res = self.make_request(self.FIND_ROLE_LIST_API_URL, data)
        
        # 检查 API 响应码是否为成功（假设 code=0 表示成功）
        if res.code != 200:
            raise KurobbsClientException(f"API 请求失败: {res.msg} (code: {res.code})")
        
        # 确保 data 是列表类型且非空
        if not isinstance(res.data, list) or len(res.data) == 0:
            raise KurobbsClientException("未找到游戏角色信息，请检查是否绑定角色")
        
        return res.data
    
    def checkin(self) -> Response:
        """Perform the check-in operation."""
        try:
            user_game_list = self.get_user_game_list(3)
            # 确保列表不为空
            first_role = user_game_list[0]
        except KurobbsClientException as e:
            self.exceptions.append(e)
            return Response(code=-1, msg=str(e))  # 返回错误响应避免后续崩溃
    
        beijing_tz = ZoneInfo('Asia/Shanghai')
        beijing_time = datetime.now(beijing_tz)
        data = {
            "gameId": first_role.get("gameId", 2),
            "serverId": first_role.get("serverId"),
            "roleId": first_role.get("roleId"),
            "userId": first_role.get("userId"),
            "reqMonth": f"{beijing_time.month:02d}",
        }
        return self.make_request(self.SIGN_URL, data)

    def sign_in(self) -> Response:
        """Perform the sign-in operation."""
        return self.make_request(self.USER_SIGN_URL, {"gameId": 2})

    def _process_sign_action(
        self,
        action_name: str,
        action_method: Callable[[], Response],
        success_message: str,
        failure_message: str,
    ):
        """
        Handle the common logic for sign-in actions.

        :param action_name: The name of the action (used to store the result).
        :param action_method: The method to call for the sign-in action.
        :param success_message: The message to log on success.
        :param failure_message: The message to log on failure.
        """
        resp = action_method()
        if resp.success:
            self.result[action_name] = success_message
        else:
            self.exceptions.append(KurobbsClientException(failure_message))

    def start(self):
        """Start the sign-in process."""
        self._process_sign_action(
            action_name="checkin",
            action_method=self.checkin,
            success_message="签到奖励签到成功",
            failure_message="签到奖励签到失败",
        )

        self._process_sign_action(
            action_name="sign_in",
            action_method=self.sign_in,
            success_message="社区签到成功",
            failure_message="社区签到失败",
        )

        self._log()

    @property
    def msg(self):
        return ", ".join(self.result.values()) + "!"

    def _log(self):
        """Log the results and raise exceptions if any."""
        if msg := self.msg:
            logger.info(msg)
        if self.exceptions:
            raise KurobbsClientException(", ".join(map(str, self.exceptions)))


def configure_logger(debug: bool = False):
    """Configure the logger based on the debug mode."""
    logger.remove()  # Remove default logger configuration
    log_level = "DEBUG" if debug else "INFO"
    logger.add(sys.stdout, level=log_level)


def main():
    """Main function to handle command-line arguments and start the sign-in process."""
    token = os.getenv("TOKEN")
    debug = os.getenv("DEBUG", False)
    configure_logger(debug=debug)

    try:
        kurobbs = KurobbsClient(token)
        kurobbs.start()
        if kurobbs.msg:
            send_bark_notification(kurobbs.msg)
    except KurobbsClientException as e:
        logger.error(str(e), exc_info=False)
        send_bark_notification("签到任务失败!")
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
