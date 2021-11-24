import oci
import re
import time
from oci.core import ComputeClient, VirtualNetworkClient
from oci.config import validate_config
import sys
import requests
import random
import base64
# tg pusher config
USE_TG = False  # 如果啟用tg推送 要設置為True
TG_BOT_TOKEN = ''  # 通過 @BotFather 申請獲得，示例：1077xxx4424:AAFjv0FcqxxxxxxgEMGfi22B4yh15R5uw
TG_USER_ID = ''  # 使用者、群組或頻道 ID，示例：129xxx206
TG_API_HOST = 'api.telegram.org'  # 自建 API 反代位址，供網路環境無法訪問時使用，網路正常則保持預設


def telegram(desp):
    data = (('chat_id', TG_USER_ID), ('text', '🐢甲骨文ARM搶注腳本為您播報🐢 \n\n' + desp))
    response = requests.post('https://' + TG_API_HOST + '/bot' + TG_BOT_TOKEN +
                             '/sendMessage',
                             data=data)
    if response.status_code != 200:
        print('Telegram Bot 推送失敗')
    else:
        print('Telegram Bot 推送成功')


class OciUser:
    """
    oci 使用者設定檔的類
    """
    user: str
    fingerprint: str
    key_file: str
    tenancy: str
    region: str

    def __init__(self, configfile="~/.oci/config", profile="DEFAULT"):
        # todo 用戶可以自訂制定config檔位址，暫時懶得寫
        cfg = oci.config.from_file(file_location=configfile,
                                   profile_name=profile)
        validate_config(cfg)
        self.parse(cfg)

    def parse(self, cfg) -> None:
        print("parser cfg")
        self.user = cfg['user']
        self.fingerprint = cfg["fingerprint"]
        self.key_file = cfg["key_file"]
        self.tenancy = cfg['tenancy']
        self.region = cfg['region']

    def keys(self):
        return ("user", "fingerprint", "key_file", "tenancy", "region")

    def __getitem__(self, item):
        return getattr(self, item)

    def compartment_id(self):
        return self.tenancy


class FileParser:
    def __init__(self, file_path: str) -> None:
        self.parser(file_path)

    def parser(self, file_path):
        # compoartment id
        # print("開始解析參數")

        try:
            print("filepath", file_path)
            f = open(file_path, "r")
            self._filebuf = f.read()
            f.close()

        except Exception as e:
            print("main.tf檔打開失敗,請再一次確認執行了正確操作,腳本退出", e)
            exit(0)

        compoartment_pat = re.compile('compartment_id = "(.*)"')
        self.compoartment_id = compoartment_pat.findall(self._filebuf).pop()

        # 記憶體
        memory_pat = re.compile('memory_in_gbs = "(.*)"')
        self.memory_in_gbs = float(memory_pat.findall(self._filebuf).pop())
        # 查找cpu個數
        cpu_pat = re.compile('ocpus = "(.*)"')
        self.ocpus = float(cpu_pat.findall(self._filebuf).pop())

        # 可用域
        ava_domain_pat = re.compile('availability_domain = "(.*)"')

        self.availability_domain = ava_domain_pat.findall(self._filebuf).pop()

        # 子網id
        subnet_pat = re.compile('subnet_id = "(.*)"')
        self.subnet_id = subnet_pat.findall(self._filebuf).pop()
        # 實例名稱
        disname_pat = re.compile('display_name = "(.*)"')
        disname = disname_pat.findall(self._filebuf).pop()
        self.display_name = disname.strip().replace(" ", "-")

        # imageid
        imageid_pat = re.compile('source_id = "(.*)"')
        self.image_id = imageid_pat.findall(self._filebuf)[0]
        # 硬碟大小
        oot_volume_size_in_gbs_pat = re.compile(
            'boot_volume_size_in_gbs = "(.*)"')
        try:
            self.boot_volume_size_in_gbs = float(
                oot_volume_size_in_gbs_pat.findall(self._filebuf).pop())
        except IndexError:
            self.boot_volume_size_in_gbs = 50.0

        # print("硬碟大小", self.boot_volume_size_in_gbs)
        # 讀取金鑰
        ssh_rsa_pat = re.compile('"ssh_authorized_keys" = "(.*)"')
        try:
            self.ssh_authorized_keys = ssh_rsa_pat.findall(self._filebuf).pop()
        except Exception as e:
            print("推薦創建堆疊的時候下載ssh key，理論上是可以不用的，但是我沒寫😂,麻煩重新創建吧")

    @property
    def ssh_authorized_keys(self):
        self._sshkey

    @ssh_authorized_keys.setter
    def ssh_authorized_keys(self, key):
        self._sshkey = key

    @property
    def boot_volume_size_in_gbs(self):
        return self._volsize

    @boot_volume_size_in_gbs.setter
    def boot_volume_size_in_gbs(self, size):
        self._volsize = size

    @property
    def image_id(self):
        return self._imgid

    @image_id.setter
    def image_id(self, imageid):
        self._imgid = imageid

    @property
    def display_name(self):
        return self._dname

    @display_name.setter
    def display_name(self, name):
        self._dname = name

    @property
    def subnet_id(self):
        return self._subid

    @subnet_id.setter
    def subnet_id(self, sid):
        self._subid = sid

    @property
    def compoartment_id(self):
        return self._comid

    @compoartment_id.setter
    def compoartment_id(self, cid):
        self._comid = cid

    @property
    def memory_in_gbs(self):
        return self._mm

    @memory_in_gbs.setter
    def memory_in_gbs(self, mm):
        self._mm = mm

    @property
    def ocpus(self):
        return self._cpu

    @ocpus.setter
    def ocpus(self, cpu_count):
        self._cpu = cpu_count

    @property
    def availability_domain(self):
        return self._adomain

    @availability_domain.setter
    def availability_domain(self, domain):
        self._adomain = domain


class InsCreate:
    shape = 'VM.Standard.A1.Flex'
    sleep_time = 5.0
    try_count = 0
    desp = ""

    def __init__(self, user: OciUser, filepath) -> None:
        self._user = user
        self._client = ComputeClient(config=dict(user))
        self.tf = FileParser(filepath)

    def gen_pwd(self):
        passwd = ''.join(
            random.sample(
                'ZYXWVUTSRQPONMLKJIHGFEDCBAzyxwvutsrqponmlkjihgfedcba#@1234567890',
                13))
        print("創建ssh登陸密碼:{}\n".format(passwd))
        self._pwd = passwd
        sh = '#!/bin/bash \n    echo root:' + passwd + " | sudo chpasswd root\n    sudo sed -i 's/^.*PermitRootLogin.*/PermitRootLogin yes/g' /etc/ssh/sshd_config;\n    sudo sed -i 's/^.*PasswordAuthentication.*/PasswordAuthentication yes/g' /etc/ssh/sshd_config;\n    sudo reboot"
        sh64 = base64.b64encode(sh.encode('utf-8'))
        sh64 = str(sh64, 'utf-8')
        self._slcmd = sh64

    def create(self):
        # print("與運行創建活動")
        # 開啟一個tg的原始推送
        text = "腳本開始啟動:\n,區域:{}-實例:{},CPU:{}C-記憶體:{}G-硬碟:{}G的小🐔已經快馬加鞭搶購了\n".format(
            self.tf.availability_domain, self.tf.display_name, self.tf.ocpus,
            self.tf.memory_in_gbs, self.tf.boot_volume_size_in_gbs)
        telegram(text)
        self.gen_pwd()
        while True:
            try:
                ins = self.lunch_instance()  # 應該返回具體的成功的資料
            except oci.exceptions.ServiceError as e:
                if e.status == 429 and e.code == 'TooManyRequests' and e.message == 'Too many requests for the user':
                    # 被限速了，改一下時間
                    print("請求太快了，自動調整請求時間ing")
                    if self.sleep_time < 60:
                        self.sleep_time += 10
                elif not (e.status == 500 and e.code == 'InternalError'
                          and e.message == 'Out of host capacity.'):
                    if "Service limit" in e.message and e.status==400:

                        # 可能是別的錯誤，也有可能是 達到上限了，要去查看一下是否開通成功，也有可能錯誤了
                        self.logp("❌如果看到這條推送,說明刷到機器，但是開通失敗了，請後臺檢查你的cpu，記憶體，硬碟佔用情況，並釋放對應的資源 返回值:{},\n 腳本停止".format(e))
                    else:
                        self.logp("❌發生錯誤,腳本停止!請檢查參數或github回饋/查找 相關問題:{}".format(e))
                    telegram(self.desp)
                    raise e
                else:
                    # 沒有被限速，恢復減少的時間
                    print("目前沒有請求限速,快馬加刷中")
                    if self.sleep_time > 15:
                        self.sleep_time -= 10
                print("本次返回資訊:",e)
                time.sleep(self.sleep_time)
            else:
                #  開通成功 ，ins 就是返回的資料
                #  可以等一會去請求實例的ip
                # print("開通成功之後的ins:\n\n", ins, type(ins))
                self.logp(
                    "🎉經過 {} 嘗試後\n 區域:{}實例:{}-CPU:{}C-記憶體:{}G🐔創建成功了🎉\n".format(
                        self.try_count + 1,
                        self.tf.availability_domain,
                        self.tf.display_name,
                        self.tf.ocpus,
                        self.tf.memory_in_gbs,
                    ))
                self.ins_id = ins.id
                self.logp("ssh登陸密碼: {} \n".format(self._pwd))
                self.check_public_ip()

                telegram(self.desp)
                break
            finally:
                self.try_count += 1
                print("搶注中，已經經過:{}嘗試".format(self.try_count))

    def check_public_ip(self):

        network_client = VirtualNetworkClient(config=dict(self._user))
        while True:
            attachments = self._client.list_vnic_attachments(
                compartment_id=self._user.compartment_id(),
                instance_id=self.ins_id)
            data = attachments.data
            if len(data) != 0:
                print("開始查找vnic id ")
                vnic_id = data[0].vnic_id
                public_ip = network_client.get_vnic(vnic_id).data.public_ip
                self.logp("公網ip為:{}\n 🐢腳本停止，感謝使用😄\n".format(public_ip))
                self.public_ip = public_ip
                break
            time.sleep(5)

    def lunch_instance(self):
        return self._client.launch_instance(
            oci.core.models.LaunchInstanceDetails(
                display_name=self.tf.display_name,
                compartment_id=self.tf.compoartment_id,
                shape=self.shape,
                extended_metadata={'user_data': self._slcmd},
                shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                    ocpus=self.tf.ocpus, memory_in_gbs=self.tf.memory_in_gbs),
                availability_domain=self.tf.availability_domain,
                create_vnic_details=oci.core.models.CreateVnicDetails(
                    subnet_id=self.tf.subnet_id,
                    hostname_label=self.tf.display_name),
                source_details=oci.core.models.InstanceSourceViaImageDetails(
                    image_id=self.tf.image_id,
                    boot_volume_size_in_gbs=self.tf.boot_volume_size_in_gbs,
                ),
                metadata=dict(ssh_authorized_keys=self.tf.ssh_authorized_keys),
                is_pv_encryption_in_transit_enabled=True,
            )).data

    def logp(self, text):
        print(text)
        if USE_TG:
            self.desp += text


if __name__ == "__main__":
    user = OciUser()
    path = sys.argv[1]
    ins = InsCreate(user, path)
    ins.create()

