import argparse
import asyncio
import multiprocessing
import shutil

import aiofiles
import requests
from aiohttp import ClientSession
from loguru import logger
from lxml import html

from settings import config


class Image(multiprocessing.Process):

    def __init__(self, task_queue, result_queue,
                 url, out_dir, mode, item):
        multiprocessing.Process.__init__(self)
        self.task_queue = task_queue
        self.result_queue = result_queue
        self.url = url
        self.out_dir = out_dir
        self.mode = mode
        self.item = item

    async def get(self, url: str, session: ClientSession, content_type) -> str:
        resp = await session.get(url)
        if resp.status != 200:
            logger.error(f'{self.name}:{url} failed, status={resp.status}')
            return 'failed'
        if content_type == 'text':
            data = await resp.text()
        else:
            data = await resp.read()
        return data

    async def aio_process(
            self,
            image_url: str,
            session: ClientSession,
            content_type: str
    ) -> str:
        img_path = f'{config["SCRAPER"]["OUT_DIR"]}/{image_url.split("/")[-1]}'
        image = await self.get(image_url, session, content_type=content_type)
        if image:
            async with aiofiles.open(img_path, "wb") as file:
                await file.write(image)
        return f'Fetch succeeded: {image_url}'

    async def asyncio_sessions(self, pages) -> None:
        tasks = []
        async with ClientSession() as session:
            for page in pages:
                response = await self.get(
                    url=config['SCRAPER']['URL'] + f'p{page}/{self.item}.html',
                    session=session,
                    content_type='text'
                )
                tree = html.fromstring(response)
                amount_pages = 1
                for page_number in range(amount_pages):
                    page_number += 1
                    for image_url in tree.xpath('//img/@src'):
                        if 'images.stockfreeimages.com' in image_url:
                            tasks.append(
                                self.aio_process(
                                    image_url, session, content_type='image'
                                )
                            )
            results = await asyncio.gather(*tasks)
        # send result status
        for r in results:
            self.result_queue.put(r)

    def sync_process(self, pages: list) -> None:
        for page in pages:
            res = requests.get(self.url + f'p{page}/{self.item}.html')
            tree = html.fromstring(res.text)
            for image_url in tree.xpath('//img/@src'):
                if 'images.stockfreeimages.com' in image_url:
                    r = requests.get(image_url, stream=True)
                    if r.status_code == 200:
                        with open(
                                f'images/{image_url.split("/")[-1]}',
                                'wb'
                        ) as f:
                            r.raw.decode_content = True
                            shutil.copyfileobj(r.raw, f)
                        self.result_queue.put(f'{page} fetch succeeded')

    def run(self):
        proc_name = self.name
        pages = []

        # Get all tasks
        while True:
            task = self.task_queue.get()
            if task == 'done':
                logger.debug(f'{proc_name} Downloaded all images')
                break
            pages.append(task)
            self.task_queue.task_done()

        logger.info(f'{proc_name} downloading {self.mode} {len(pages)} images')
        # Do sync or async processing
        if self.mode == "async":
            asyncio.run(self.asyncio_sessions(pages))
        else:
            self.sync_process(pages)
        self.task_queue.task_done()

    def __str__(self):
        return 'Image %s.' % self.name


def parse_cli_args():
    mparser = argparse.ArgumentParser(
        description='Evaluate sync vs async multiprocessing')
    mparser.add_argument('-m',
                         '--mode',
                         action='store',
                         default='async',
                         choices=['sync', 'async'],
                         help='evaluation mode')

    mparser.add_argument('-p',
                         '--process',
                         action='store',
                         type=int,
                         default=4,
                         help='multiprocessing count')

    return mparser.parse_args()


def main():

    args = parse_cli_args()

    process_count = args.parallel
    url = config['SCRAPER']['URL']
    out_dir = config['SCRAPER']['OUT_DIR']
    amount_pages = config['SCRAPER']['AMOUNT_PAGES']
    item = config['SCRAPER']['ITEM']

    response = requests.get(f'{url}/p1/{item}.html')
    tree = html.fromstring(response.text)
    amount_pages_on_site = int(
        tree.xpath('//li[@class="pag-text"]/text()')[0].split()[1]
    )
    if amount_pages > amount_pages_on_site:
        amount_pages = amount_pages_on_site

    logger.info(f'Processing {args.mode} {amount_pages} images')

    task_queue = multiprocessing.JoinableQueue()
    result_queue = multiprocessing.Queue()
    if process_count < multiprocessing.cpu_count():
        process_count = multiprocessing.cpu_count()
    logger.info(f'Spawning {process_count} gatherers...')

    images = [
        Image(task_queue, result_queue, url, out_dir, args.mode, item)
        for _ in range(process_count)
    ]

    for image in images:
        image.start()

    for page_number in range(amount_pages):
        task_queue.put(page_number + 1)

    for _ in range(process_count):
        task_queue.put('done')

    fail_count = sum(
        1 for _ in range(amount_pages) if 'failed' in result_queue.get()
    )
    logger.info(
        f'Done, success: {amount_pages - fail_count}/{amount_pages}, '
        f'failure: {fail_count}/{amount_pages}'
    )


if __name__ == '__main__':
    main()
