from __future__ import annotations

import dataclasses
import json
import logging
import os
from datetime import datetime
from datetime import timedelta
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, Set

import requests
import ics


ICS_AUTHOR = "상명대학교<@smu.ac.kr>, 김동주<hepheir@gmail.com>"
ICS_FILE_OUTPUT_PATH = "docs/calendar.ics"

CURRENT_YEAR = datetime.now().year
TARGET_YEARS = [
    CURRENT_YEAR-1,
    CURRENT_YEAR,
    CURRENT_YEAR+1,
]
ADDITIONAL_TARGET_YEARS = [
    CURRENT_YEAR-3,
    CURRENT_YEAR-2,
    CURRENT_YEAR+2,
]


logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] [%(name)-24s] [%(levelname)-8s]: %(message)s',
)

logger = logging.getLogger('smu-calendar')


def main():
    icalendar = ics.icalendar.Calendar(creator=ICS_AUTHOR)
    events = fetch_events()

    for evt in sorted(events):
        icalendar.events.add(evt.to_ics())

    logger.info(f'📋 writing events on "{ICS_FILE_OUTPUT_PATH}".')

    if not os.path.exists(os.path.dirname(ICS_FILE_OUTPUT_PATH)):
        os.makedirs(os.path.dirname(ICS_FILE_OUTPUT_PATH))

    with open(ICS_FILE_OUTPUT_PATH, 'w') as f:
        f.writelines(icalendar.serialize_iter())


def fetch_events() -> Set[SmuCalendarEvent]:
    crawler = SmuCalendarCrawler()
    events: Set[SmuCalendarEvent] = set()

    for year in TARGET_YEARS:
        try:
            logger.info(f'🌀 start crawling {year} events.')
            events.update(crawler.get_events(year))
        except Exception:
            logger.error(f'❌ failed to crawl {year} events.')
        else:
            logger.info(f'✅ crawled {year} events successfully.')

    for year in ADDITIONAL_TARGET_YEARS:
        try:
            logger.info(f'start crawling {year} events. (additional)')
            events.update(crawler.get_events(year))
        except Exception:
            logger.warning(f'⚠️ failed to crawl {year} events. (additional)')
        else:
            logger.info(f'✅ crawled {year} events successfully. (additional)')

    return events


class HTMLTagRemover(HTMLParser):
    def __init__(self, *, convert_charrefs: bool = True) -> None:
        super().__init__(convert_charrefs=convert_charrefs)
        self.results = ''

    def handle_data(self, data: str) -> None:
        self.results += data


@dataclasses.dataclass
class SmuCalendarEvent:
    boardNo: str        # e.g. "85"
    articleNo: int      # e.g. 732882
    articleTitle: str   # e.g. "2023-2학기 성적입력"
    articleText: str    # e.g. "<div class=\"fr-view\"><p>2023-2학기 성적입력</p></div>"
    createDt: int       # e.g. 1672028823000
    orderDt: int        # e.g. 1672028823000
    updateDt: int       # e.g. 1674201156000
    etcChar4: str       # e.g. "2022"
    etcChar5: str       # e.g. "second_term"
    etcChar6: str       # e.g. "2023-12-11"
    etcChar7: str       # e.g. "2024-01-01"
    etcChar8: str       # e.g. "bachelor"
    etcChar9: str       # e.g. "seoul"

    def __hash__(self) -> int:
        return self.articleNo

    def __lt__(self, other: SmuCalendarEvent) -> bool:
        return self.articleNo < other.articleNo

    def to_ics(self) -> ics.Event:
        # TODO:
        #   일부 이벤트는 시작일이 종료일보다 먼저라서 오류로 ics.Event 클래스 초기화에 실패함.
        #   그러나, 학교 홈페이지 학사일정 상에는 당일 이벤트로 올라와 있는 경우가 있음.
        #   당일 일정이므로 종료일에 시작일과 종료일 중 최댓값을 대입하여 임시 방편으로 예외처리 해두었으나,
        #   좋은 방법은 아닌 것 같음. *추후 수정 요함.
        event = ics.Event(
            uid=str(self.articleNo),
            name=self.articleTitle,
            description=self._cleanhtml(self.articleText),
            begin=self._strptime(self.etcChar6),
            end=max(self._strptime(self.etcChar6), self._strptime(self.etcChar7)),
            created=self._msptime(self.createDt),
            last_modified=self._msptime(self.updateDt),
            url=f'https://www.smu.ac.kr/kor/life/academicCalendar.do?mode=view&articleNo={self.articleNo}&boardNo={self.boardNo}',
        )
        event.make_all_day()
        return event

    def _strptime(self, s: str) -> datetime:
        return datetime.strptime(s, "%Y-%m-%d")

    def _msptime(self, ms: int) -> datetime:
        return datetime(1970, 1, 1) + timedelta(milliseconds=ms)

    def _cleanhtml(self, html: str) -> str:
        remover = HTMLTagRemover()
        remover.feed(html)
        return remover.results


class SmuCalendarCrawler:
    def get_events(self, year: int) -> Set[SmuCalendarEvent]:
        return set(self._get_events(year))

    def _get_events(self, year: int) -> Iterable[SmuCalendarEvent]:
        raw_data = self._fetch(year)
        self._validate(raw_data)
        return self._deserialize(raw_data)

    def _fetch(self, year: int) -> Dict[str, Any]:
        response = requests.post(
            url="https://www.smu.ac.kr/app/common/selectDataList.do",
            data={
                'sqlId': 'jw.Article.selectCalendarArticle',
                'modelNm': 'list',
                'jsonStr': json.dumps({
                    "year": str(year),
                    "bachelorBoardNoList": ["85"],
                }),
            }
        )
        return response.json()

    def _validate(self, json: Dict[str, Any]):
        assert json['success'] is True
        assert isinstance(json['list'], list)

    def _deserialize(self, json: Dict[str, Any]) -> Iterable[SmuCalendarEvent]:
        for item in json['list']:
            yield SmuCalendarEvent(
                boardNo=item['boardNo'],
                articleNo=item['articleNo'],
                articleTitle=item['articleTitle'],
                articleText=item['articleText'],
                createDt=item['createDt'],
                orderDt=item['orderDt'],
                updateDt=item['updateDt'],
                etcChar4=item['etcChar4'],
                etcChar5=item['etcChar5'],
                etcChar6=item['etcChar6'],
                etcChar7=item['etcChar7'],
                etcChar8=item['etcChar8'],
                etcChar9=item['etcChar9'],
            )


if __name__ == "__main__":
    main()
