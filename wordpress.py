import xmlrpc.client


class WordPressClient:
    def __init__(self, url: str, username: str, password: str):
        if not url.endswith("/xmlrpc.php"):
            url = url.rstrip("/") + "/xmlrpc.php"
        self.rpc = xmlrpc.client.ServerProxy(url, allow_none=True)
        self.username = username
        self.password = password

    def test(self) -> dict:
        return self.rpc.wp.getProfile(1, self.username, self.password)

    def get_link(self, post_id: str) -> str:
        info = self.rpc.wp.getPost(1, self.username, self.password, str(post_id), ["link"])
        return info.get("link", "")

    def new_post(
        self,
        title: str,
        content: str,
        categories: list[str] | None = None,
        tags: list[str] | None = None,
        comment_status: str = "open",
        post_status: str = "publish",
    ) -> str:
        data: dict = {
            "post_title": title,
            "post_content": content,
            "post_status": post_status,
            "comment_status": comment_status,
        }
        terms: dict = {}
        if categories:
            terms["category"] = categories
        if tags:
            terms["post_tag"] = tags
        if terms:
            data["terms_names"] = terms

        return self.rpc.wp.newPost(1, self.username, self.password, data)
