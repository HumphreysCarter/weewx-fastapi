# Carter Humphreys
# https://github.com/HumphreysCarter/weewx-fastapi

from weecfg.extension import ExtensionInstaller


class WeeWxApiInstaller(ExtensionInstaller):
    def __init__(self):
        # Create weewx config
        super(WeeWxApiInstaller, self).__init__(
            version='0.1.0',
            name='weewx-fastapi',
            description='An API interface to WeeWX utilizing the FastAPI framework.',
            author='Carter Humphreys',
            author_email='carter.humphreys@lake-effect.dev',
            data_services='user.api_server.DataAPI',
            config={
                'DataAPI': {
                    'enable': 'True',
                    'server_host': 'localhost',
                    'server_port': 8000,
                },
            },
            files=[
                (
                    'bin/user/', ['bin/user/api_server.py', 'bin/user/api_router.py']
                ),
            ]
        )
